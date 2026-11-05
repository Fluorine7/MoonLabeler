// SPDX-License-Identifier: GPL-3.0-or-later
#include "Internal.hpp"
#include <SpiceUsr.h>
#include <erfa.h>
#include <fitsio.h>
#include <archive.h>
#include <archive_entry.h>
#include <algorithm>
#include <fstream>
#include <mutex>
#include <numeric>
#include <regex>
#include <map>
#include <csetjmp>
#include <jpeglib.h>
#include <sstream>

extern "C" char *mn_binary_contours(const uint8_t *mask,int width,int height,char error[1024]) {
    try {
        if(!mask||width<2||height<2||width>8192||height>8192)throw std::runtime_error("轮廓图像尺寸无效。");
        std::vector<std::vector<cv::Point>> contours;
        cv::findContours(cv::Mat(height,width,CV_8UC1,const_cast<uint8_t*>(mask)).clone(),contours,cv::RETR_EXTERNAL,cv::CHAIN_APPROX_SIMPLE);
        std::ostringstream text;text<<'[';bool first=true;
        for(const auto &contour:contours) {
            if(cv::contourArea(contour)<=1)continue;
            std::vector<cv::Point> polygon;cv::approxPolyDP(contour,polygon,1.,true);if(polygon.empty())continue;
            if(!first)text<<',';first=false;text<<'[';
            for(size_t i=0;i<=polygon.size();++i){if(i)text<<',';auto p=polygon[i%polygon.size()];text<<'['<<p.x<<','<<p.y<<']';}
            text<<']';
        }
        text<<']';auto value=text.str();auto *result=static_cast<char*>(malloc(value.size()+1));if(!result)throw std::bad_alloc();
        memcpy(result,value.c_str(),value.size()+1);return result;
    }catch(const std::exception &e){problem(error,e);return nullptr;}
}

// The pinned CSPICE f2c runtime defaults OLD files to r+b / r+. This embedder
// only reads kernels; request input access directly rather than write access
// to files inside a signed application bundle. Symbols come from f2c open.c.
extern "C" { extern char *f__r_mode[2]; extern char *f__w_mode[4]; }

namespace {
struct JPEGError { jpeg_error_mgr standard; jmp_buf jump; char message[JMSG_LENGTH_MAX]; };
void jpegFailure(j_common_ptr info) {
    auto *error=reinterpret_cast<JPEGError *>(info->err);(*info->err->format_message)(info,error->message);longjmp(error->jump,1);
}
}
extern "C" uint8_t *mn_read_jpeg(const char *path,int *width,int *height,char error[1024]) {
    FILE *file=fopen(path,"rb");if(!file){snprintf(error,1024,"Cannot open JPEG.");return nullptr;}
    jpeg_decompress_struct decoder{};JPEGError failure{};decoder.err=jpeg_std_error(&failure.standard);failure.standard.error_exit=jpegFailure;
    uint8_t * volatile output=nullptr;
    if(setjmp(failure.jump)){jpeg_destroy_decompress(&decoder);fclose(file);free(output);snprintf(error,1024,"JPEG: %s",failure.message);return nullptr;}
    jpeg_create_decompress(&decoder);jpeg_stdio_src(&decoder,file);jpeg_read_header(&decoder,TRUE);
    const bool cmyk=decoder.jpeg_color_space==JCS_CMYK || decoder.jpeg_color_space==JCS_YCCK;
    decoder.out_color_space=cmyk?JCS_CMYK:JCS_EXT_RGBA;decoder.dct_method=JDCT_ISLOW;
    jpeg_start_decompress(&decoder);
    if(double(decoder.output_width)*decoder.output_height>160000000){jpeg_destroy_decompress(&decoder);fclose(file);snprintf(error,1024,"JPEG dimensions exceed limit.");return nullptr;}
    *width=(int)decoder.output_width;*height=(int)decoder.output_height;output=(uint8_t *)malloc(size_t(*width)*(*height)*4);
    if(!output){jpeg_destroy_decompress(&decoder);fclose(file);snprintf(error,1024,"JPEG allocation failed.");return nullptr;}
    while(decoder.output_scanline<decoder.output_height){JSAMPROW row=output+size_t(decoder.output_scanline)*(*width)*4;jpeg_read_scanlines(&decoder,&row,1);}
    if(cmyk) for(size_t i=0;i<size_t(*width)*(*height);++i) {
        auto *pixel=output+i*4;int black=decoder.saw_Adobe_marker?pixel[3]:255-pixel[3];
        for(int c=0;c<3;++c) pixel[c]=(uint8_t)(((decoder.saw_Adobe_marker?pixel[c]:255-pixel[c])*black+127)/255);
        pixel[3]=255;
    }
    jpeg_finish_decompress(&decoder);jpeg_destroy_decompress(&decoder);fclose(file);return output;
}

extern "C" {
MNTask *mn_task_create() { return new MNTask; }
void mn_task_cancel(MNTask *task) { if(task) task->cancelled.store(true); }
int mn_task_cancelled(MNTask *task) { return task && task->cancelled.load(); }
void mn_task_destroy(MNTask *task) { delete task; }
void mn_free(void *p) { free(p); }
uint8_t *mn_resize_rgba(const uint8_t *photo,int width,int height,int outWidth,int outHeight,char error[1024]) {
    try {
        if(width<=0||height<=0||outWidth<=0||outHeight<=0)throw std::runtime_error("图像尺寸无效。");
        cv::Mat input(height,width,CV_8UC4,const_cast<uint8_t *>(photo)),output;
        cv::resize(input,output,{outWidth,outHeight},0,0,cv::INTER_AREA);
        auto *result=(uint8_t *)malloc(output.total()*4);if(!result)throw std::bad_alloc();memcpy(result,output.data,output.total()*4);return result;
    }catch(const std::exception &e){problem(error,e);return nullptr;}
}
}

namespace {
std::mutex spiceMutex;
void spiceCheck() {
    if(failed_c()) { char message[1841]; getmsg_c("LONG",1840,message); reset_c(); throw std::runtime_error(message); }
}
cv::Vec3d unit(cv::Vec3d value) { double n=cv::norm(value); if(n<1e-12) throw std::runtime_error("方向向量无效。"); return value/n; }
cv::Mat fit(const std::vector<cv::Point2d>& source,const std::vector<cv::Point2d>& target,int mirror,double &rms) {
    if(source.size()!=target.size() || source.size()<2) throw std::runtime_error("至少需要两个有效的参考点。");
    cv::Point2d mean{},tm{};
    for(size_t i=0;i<source.size();++i) { mean+=source[i]; tm+=target[i]; }
    mean*=1./source.size(); tm*=1./source.size();
    cv::Mat centered((int)source.size(),2,CV_64F);
    double variance=0,spread=0;
    for(size_t i=0;i<source.size();++i) {
        auto p=source[i]-mean; centered.at<double>((int)i,0)=p.x; centered.at<double>((int)i,1)=p.y;
        variance+=p.dot(p); spread=std::max(spread,cv::norm(target[i]-tm));
    }
    if(variance<1e-10 || spread<1) throw std::runtime_error("参考点太接近，请选择分布更广的地形。");
    cv::SVD svd(centered);
    if(source.size()>=3 && svd.w.at<double>(1)<.01*svd.w.at<double>(0)) throw std::runtime_error("参考点接近一条直线，请加入不共线的地形点。");
    rms=INFINITY; cv::Mat best;
    for(int sign:{1,-1}) {
        if((mirror==1 && sign==1)||(mirror==0 && sign==-1)||(source.size()==2 && mirror!=1 && sign==-1)) continue;
        cv::Mat design=cv::Mat::zeros((int)source.size()*2,4,CV_64F),targets((int)source.size()*2,1,CV_64F),solution;
        for(size_t i=0;i<source.size();++i) {
            double x=sign*source[i].x,y=source[i].y;
            design.at<double>(2*i,0)=x; design.at<double>(2*i,1)=-y; design.at<double>(2*i,2)=1;
            design.at<double>(2*i+1,0)=y; design.at<double>(2*i+1,1)=x; design.at<double>(2*i+1,3)=1;
            targets.at<double>(2*i)=target[i].x; targets.at<double>(2*i+1)=target[i].y;
        }
        if(!cv::solve(design,targets,solution,cv::DECOMP_SVD)) continue;
        double a=solution.at<double>(0),b=solution.at<double>(1);
        cv::Mat m=(cv::Mat_<double>(2,3)<<a*sign,-b,solution.at<double>(2),b*sign,a,solution.at<double>(3));
        double cost=0;
        for(size_t i=0;i<source.size();++i) { auto d=transform(m,source[i])-target[i]; cost+=d.dot(d); }
        cost=sqrt(cost/source.size()); if(cost<rms) { rms=cost; best=m; }
    }
    if(best.empty()) throw std::runtime_error("无法拟合参考点。"); return best;
}
}

extern "C" int mn_ephemeris(const char *folder,const char *utc,double latitude,double longitude,
                             int topocentric,double deltaT,double out[13],char error[1024]) {
    std::lock_guard<std::mutex> lock(spiceMutex);
    try {
        f__w_mode[2]=f__r_mode[0]; f__w_mode[3]=f__r_mode[1];
        char action[]="RETURN",print[]="NONE"; erract_c("SET",0,action); errprt_c("SET",0,print);
        static std::string loaded;
        if(loaded!=folder) {
            kclear_c();
            for(const char *name:{"naif0012.tls","de421.bsp","moon_080317.tf","pck00008.tpc","moon_pa_de421_1900-2050.bpc"}) {
                std::string path=std::string(folder)+"/"+name; furnsh_c(path.c_str()); spiceCheck();
            }
            loaded=folder;
        }
        double et=0,lightTime=0,position[3],sunPosition[3],rotation[3][3];
        str2et_c(utc,&et); spiceCheck();
        spkpos_c("EARTH",et,"J2000","NONE","MOON",position,&lightTime); spiceCheck();
        spkpos_c("SUN",et,"J2000","NONE","MOON",sunPosition,&lightTime); spiceCheck();
        if(topocentric) {
            double station[3],earth[3][3];
            if(eraGd2gc(1,longitude*M_PI/180,latitude*M_PI/180,0,station)) throw std::runtime_error("拍摄地点无效。");
            double tt=unitim_c(et,"ET","TDT")/86400;
            eraC2t06a(2451545,tt,2451545,tt-deltaT/86400,0,0,earth);
            for(int i=0;i<3;++i) for(int j=0;j<3;++j) position[i]+=earth[j][i]*station[j]/1000;
        }
        cv::Vec3d raw(position[0],position[1],position[2]); double distance=cv::norm(raw);
        auto obs=unit(raw),north=unit(cv::Vec3d(0,0,1)-obs[2]*obs),right=unit(north.cross(obs));
        auto sunlight=unit(cv::Vec3d(sunPosition[0],sunPosition[1],sunPosition[2]));
        pxform_c("J2000","MOON_ME",et,rotation); spiceCheck();
        cv::Vec3d vectors[]={obs,right,north,sunlight};
        for(int v=0;v<4;++v) for(int i=0;i<3;++i) { out[v*3+i]=0; for(int j=0;j<3;++j) out[v*3+i]+=rotation[i][j]*vectors[v][j]; }
        out[12]=distance; return 1;
    } catch(const std::exception &e) { problem(error,e); return 0; }
}

extern "C" int mn_fit_similarity(const double *src,const double *dst,int count,int mirror,
                                  double matrix[6],double *rms,double *residuals,double *checks,int *suspect,char error[1024]) {
    try {
        std::vector<cv::Point2d> source,target;
        for(int i=0;i<count;++i) {
            for(int j=0;j<2;++j) if(!std::isfinite(src[2*i+j])||!std::isfinite(dst[2*i+j])) throw std::runtime_error("参考点无效。");
            source.emplace_back(src[2*i],src[2*i+1]); target.emplace_back(dst[2*i],dst[2*i+1]);
        }
        double cost; auto m=fit(source,target,mirror,cost); memcpy(matrix,m.ptr<double>(),6*sizeof(double)); *rms=cost; *suspect=-1;
        std::vector<std::pair<double,int>> alternatives;
        for(int i=0;i<count;++i) {
            if(residuals) residuals[i]=cv::norm(transform(m,source[i])-target[i]);
            if(checks) checks[i]=NAN;
            if(count<4 || !checks) continue;
            auto s=source,t=target; s.erase(s.begin()+i); t.erase(t.begin()+i);
            try { double other; auto candidate=fit(s,t,mirror,other);
                if(checks) checks[i]=cv::norm(transform(candidate,source[i])-target[i]); alternatives.emplace_back(other,i);
            } catch(...) {}
        }
        std::sort(alternatives.begin(),alternatives.end());
        if(count>=5 && alternatives.size()>=2 && cost>2 && alternatives[0].first<.3*cost &&
           alternatives[1].first>std::max(1.,2*alternatives[0].first) && checks && checks[alternatives[0].second]>std::max(5.,4*alternatives[0].first)) *suspect=alternatives[0].second;
        return 1;
    } catch(const std::exception &e) { problem(error,e); return 0; }
}

extern "C" double *mn_read_fits(const char *path,int *width,int *height,int *channels,char error[1024]) {
    fitsfile *file=nullptr; int status=0; double *result=nullptr;
    try {
        fits_open_file(&file,path,READONLY,&status);
        if(status) throw std::runtime_error("无法打开 FITS 文件。");
        int count=0; fits_get_num_hdus(file,&count,&status);
        for(int hdu=1;hdu<=count;++hdu) {
            int type=0,dimensions=0;
            fits_movabs_hdu(file,hdu,&type,&status); fits_get_img_dim(file,&dimensions,&status);
            if(status) {status=0;continue;}
            if(dimensions<2) continue;
            std::vector<long> axes(dimensions,1);
            fits_get_img_size(file,dimensions,axes.data(),&status);
            if(status) throw std::runtime_error("无法读取 FITS 图像尺寸。");
            std::vector<int> active;for(int i=0;i<dimensions;++i)if(axes[i]>1)active.push_back(i);
            if(active.size()<2||active.size()>3)throw std::runtime_error("FITS 需要二维灰度图或 RGB 图像。");
            int planes=1,colorAxis=-1;long columns=axes[active[0]],rows=axes[active[1]];
            if(active.size()==3) {
                // Match Python's squeezed array: prefer a leading channel
                // dimension, then accept channels in the last dimension.
                long leading=axes[active[2]],trailing=axes[active[0]];
                if(leading==3||leading==4) {planes=(int)leading;colorAxis=active[2];}
                else if(trailing==3||trailing==4) {planes=(int)trailing;colorAxis=active[0];columns=axes[active[1]];rows=axes[active[2]];}
                else throw std::runtime_error("FITS 需要二维灰度图或 RGB 图像。");
            }
            if(columns<1 || rows<1 || columns>100000 || rows>100000 || double(columns)*rows>160000000) throw std::runtime_error("FITS 图像尺寸超出范围。");
            size_t size=size_t(columns)*rows*planes;
            result=static_cast<double *>(malloc(size*sizeof(double))); if(!result) throw std::bad_alloc();
            double null=NAN;int anyNull=0,bitpix=0;fits_get_img_type(file,&bitpix,&status);
            // Floating-point NaN and infinities must reach the display
            // stretch unchanged. Integer BLANK pixels still become NaN.
            void *nullValue=bitpix>0?&null:nullptr;
            if(colorAxis<0 || colorAxis!=active[0]) fits_read_img(file,TDOUBLE,1,(LONGLONG)size,nullValue,result,&anyNull,&status);
            else {
                // Linear rows also support extra singleton axes without the
                // subset reader's axis limit or a full-size transpose buffer.
                std::vector<double> row(size_t(columns)*planes);
                size_t pixels=size_t(columns)*rows;
                for(long y=0;y<rows;++y) {
                    fits_read_img(file,TDOUBLE,1+(LONGLONG)y*columns*planes,(LONGLONG)row.size(),nullValue,row.data(),&anyNull,&status);
                    if(status) break;
                    for(long x=0;x<columns;++x)for(int plane=0;plane<planes;++plane)
                        result[size_t(plane)*pixels+size_t(y)*columns+x]=row[size_t(x)*planes+plane];
                }
            }
            if(status) throw std::runtime_error("FITS 像素读取失败。");
            *width=(int)columns; *height=(int)rows; *channels=planes;
            fits_close_file(file,&status); return result;
        }
        throw std::runtime_error("FITS 文件没有可用的二维图像。");
    } catch(const std::exception &e) { if(file) {int closeStatus=0;fits_close_file(file,&closeStatus);} free(result); problem(error,e); return nullptr; }
}

namespace {
struct Npy { std::vector<uint8_t> bytes; size_t offset=0; std::vector<int> shape; std::string type; bool fortran=false; };
Npy npy(std::vector<uint8_t> bytes) {
    if(bytes.size()<12 || memcmp(bytes.data(),"\x93NUMPY",6)) throw std::runtime_error("NPZ 中的 NPY 数据无效。");
    bool modern=bytes[6]>=2; size_t skip=modern?12:10;
    uint32_t length=bytes[8]|uint32_t(bytes[9])<<8;
    if(modern) length|=uint32_t(bytes[10])<<16|uint32_t(bytes[11])<<24;
    if(skip+length>bytes.size()) throw std::runtime_error("NPY 数据长度无效。");
    std::string header(reinterpret_cast<char *>(bytes.data()+skip),length); std::smatch match;
    if(!std::regex_search(header,match,std::regex("'descr'\\s*:\\s*'([^']+)'"))) throw std::runtime_error("NPY 数据类型缺失。");
    Npy result;result.type=match[1];result.offset=skip+length;
    result.fortran=header.find("True")!=std::string::npos;
    if(std::regex_search(header,match,std::regex("'shape'\\s*:\\s*\\(([^)]*)\\)"))) {
        std::string dims=match[1]; std::regex number("[0-9]+");
        for(auto i=std::sregex_iterator(dims.begin(),dims.end(),number);i!=std::sregex_iterator();++i) result.shape.push_back(std::stoi(i->str()));
    }
    result.bytes=std::move(bytes);return result;
}
double npyNumber(const Npy &value,size_t index) {
    int size=value.type.back()-'0';
    if(size<1||size>8)throw std::runtime_error("NPY 数据类型宽度无效。");
    if(value.offset+(index+1)*size>value.bytes.size()) throw std::runtime_error("NPY 像素不足。");
    uint8_t bytes[8]={}; memcpy(bytes,value.bytes.data()+value.offset+index*size,size);
    if(value.type[0]=='>') std::reverse(bytes,bytes+size);
    if(value.type.find('f')!=std::string::npos) { if(size==4) {float v;memcpy(&v,bytes,4);return v;} if(size==8) {double v;memcpy(&v,bytes,8);return v;} }
    if(value.type.find('i')!=std::string::npos) { if(size==1)return (int8_t)bytes[0];if(size==2) {int16_t v;memcpy(&v,bytes,2);return v;} if(size==4) {int32_t v;memcpy(&v,bytes,4);return v;} if(size==8) {int64_t v;memcpy(&v,bytes,8);return double(v);} }
    if(value.type.find('u')!=std::string::npos||value.type.find('b')!=std::string::npos) {uint64_t v=0;memcpy(&v,bytes,size);return double(v);}
    throw std::runtime_error("DEM 的 NPY 数值类型不受支持。");
}
}
extern "C" uint8_t *mn_zip_member(const char *path,const char *suffix,size_t *length,char error[1024]) {
    auto *reader=archive_read_new();archive_read_support_format_zip(reader);archive_read_support_filter_all(reader);uint8_t *result=nullptr;
    try {
        if(archive_read_open_filename(reader,path,65536)!=ARCHIVE_OK)throw std::runtime_error("无法打开目录压缩文件。");
        archive_entry *entry;std::string ending(suffix);
        while(archive_read_next_header(reader,&entry)==ARCHIVE_OK){std::string name=archive_entry_pathname(entry);std::transform(name.begin(),name.end(),name.begin(),[](unsigned char c){return (char)tolower(c);});
            if(name.size()<ending.size()||name.substr(name.size()-ending.size())!=ending){archive_read_data_skip(reader);continue;}
            auto size=archive_entry_size(entry);if(size<=0||size>32*1024*1024)throw std::runtime_error("目录文件大小无效。");*length=(size_t)size;result=(uint8_t *)malloc(*length);if(!result)throw std::bad_alloc();
            size_t offset=0;while(offset<*length){auto got=archive_read_data(reader,result+offset,*length-offset);if(got<=0)throw std::runtime_error("目录文件不完整。");offset+=(size_t)got;}
            archive_read_free(reader);return result;
        }
        throw std::runtime_error("压缩包中缺少地名数据库。");
    }catch(const std::exception &e){archive_read_free(reader);free(result);problem(error,e);return nullptr;}
}

extern "C" float *mn_read_npz(const char *path,int *rows,int *columns,double metadata[3],char error[1024]) {
    auto *archive=archive_read_new(); archive_read_support_format_zip(archive); archive_read_support_filter_all(archive);
    float *result=nullptr;
    try {
        if(archive_read_open_filename(archive,path,65536)!=ARCHIVE_OK) throw std::runtime_error("无法打开 NPZ 高程文件。");
        std::map<std::string,Npy> entries; struct archive_entry *entry;
        while(archive_read_next_header(archive,&entry)==ARCHIVE_OK) {
            std::string name=archive_entry_pathname(entry);
            if(name!="height_km.npy" && name!="north.npy" && name!="west.npy" && name!="pixels_per_degree.npy") {archive_read_data_skip(archive);continue;}
            auto length=archive_entry_size(entry);
            if(length<0 || length>1024LL*1024*1024) throw std::runtime_error("NPZ 数据大小无效。");
            std::vector<uint8_t> data((size_t)length); size_t offset=0;
            while(offset<data.size()) { auto got=archive_read_data(archive,data.data()+offset,data.size()-offset); if(got<=0) throw std::runtime_error("NPZ 数据不完整。"); offset+=got; }
            entries.emplace(name,npy(std::move(data)));
        }
        for(auto name:{"height_km.npy","north.npy","west.npy","pixels_per_degree.npy"}) if(!entries.count(name)) throw std::runtime_error("NPZ 缺少高度或经纬度元数据。");
        const auto &height=entries.at("height_km.npy");
        if(height.shape.size()!=2 || height.shape[0]<2 || height.shape[1]<2) throw std::runtime_error("DEM 需要二维高程网格。");
        *rows=height.shape[0]; *columns=height.shape[1];
        size_t count=size_t(*rows)*size_t(*columns);int itemSize=height.type.back()-'0';if(itemSize<1||itemSize>8||count>(height.bytes.size()-height.offset)/(size_t)itemSize)throw std::runtime_error("NPZ 高程维度与像素长度不一致。");
        result=static_cast<float *>(malloc(count*sizeof(float)));if(!result)throw std::bad_alloc();
        for(size_t i=0;i<count;++i) result[i]=(float)npyNumber(height,height.fortran?(i%(*columns))*(*rows)+i/(*columns):i);
        metadata[0]=npyNumber(entries.at("north.npy"),0);metadata[1]=npyNumber(entries.at("west.npy"),0);metadata[2]=npyNumber(entries.at("pixels_per_degree.npy"),0);
        archive_read_free(archive);return result;
    } catch(const std::exception &e) {archive_read_free(archive);free(result);problem(error,e);return nullptr;}
}

extern "C" uint8_t *mn_lightness(const uint8_t *photo,int width,int height,int channels,int *automatic,char error[1024]) {
    try {
        cv::Mat values=gray(photo,width,height,channels).clone();
        cv::GaussianBlur(values,values,cv::Size(),std::max(.8,std::min(width,height)*.006));
        cv::Mat selected; double otsu=cv::threshold(values,selected,0,255,cv::THRESH_BINARY|cv::THRESH_OTSU);
        *automatic=(int)std::clamp(otsu,8.,120.);
        auto *result=static_cast<uint8_t *>(malloc(size_t(width)*height));if(!result)throw std::bad_alloc();
        memcpy(result,values.data,size_t(width)*height);return result;
    } catch(const std::exception &e) {problem(error,e);return nullptr;}
}
extern "C" uint8_t *mn_coverage(const uint8_t *values,int width,int height,int level,char error[1024]) {
    try {
        cv::Mat light(height,width,CV_8U,const_cast<uint8_t *>(values)),mask,alpha=cv::Mat::zeros(height,width,CV_8U);
        cv::compare(light,level,mask,cv::CMP_GE);
        cv::morphologyEx(mask,mask,cv::MORPH_CLOSE,cv::Mat::ones(3,3,CV_8U));
        std::vector<std::vector<cv::Point>> contours;cv::findContours(mask,contours,cv::RETR_EXTERNAL,cv::CHAIN_APPROX_SIMPLE);
        for(size_t i=0;i<contours.size();++i) if(cv::contourArea(contours[i])>=3) cv::drawContours(alpha,contours,(int)i,cv::Scalar(255),cv::FILLED);
        cv::GaussianBlur(alpha,alpha,cv::Size(),std::max(.8,std::min(width,height)*.008));
        auto *result=static_cast<uint8_t *>(malloc(size_t(width)*height));if(!result)throw std::bad_alloc();
        memcpy(result,alpha.data,size_t(width)*height);return result;
    } catch(const std::exception &e) {problem(error,e);return nullptr;}
}
extern "C" double mn_correlation(const uint8_t *a,const uint8_t *b,const uint8_t *mask,int count) {
    double sa=0,sb=0,saa=0,sbb=0,sab=0,n=0;
    for(int i=0;i<count;++i) if(!mask||mask[i]) {double x=a[i],y=b[i];sa+=x;sb+=y;saa+=x*x;sbb+=y*y;sab+=x*y;++n;}
    double denominator=sqrt(std::max(0.,(n*saa-sa*sa)*(n*sbb-sb*sb)));
    return n>1 && denominator>1e-8 ? (n*sab-sa*sb)/denominator:-1;
}

// SPDX-License-Identifier: GPL-3.0-or-later
#include "Internal.hpp"
#include "EyepieceModel.hpp"
#include <opencv2/ximgproc/edge_drawing.hpp>
#include <opencv2/flann.hpp>
#include <algorithm>
#include <numeric>
#include <random>
#include <set>
#include <array>
#include <map>

namespace {
cv::Mat enhanced(const uint8_t *pixels,int width,int height,int channels,double &scale) {
    auto image=gray(pixels,width,height,channels);scale=std::min(1.,2200./std::max(width,height));
    if(scale<1)cv::resize(image,image,cv::Size(),scale,scale,cv::INTER_AREA);
    cv::Mat result;cv::createCLAHE(2.,{8,8})->apply(image,result);return result;
}
double correlation(const cv::Mat &a,const cv::Mat &b,const cv::Mat &mask) {
    cv::Scalar ma,sa,mb,sb;cv::meanStdDev(a,ma,sa,mask);cv::meanStdDev(b,mb,sb,mask);
    if(sa[0]<1e-8||sb[0]<1e-8)return -1;
    cv::Mat x,y,product;a.convertTo(x,CV_32F);b.convertTo(y,CV_32F);product=(x-ma[0]).mul(y-mb[0]);
    return cv::mean(product,mask)[0]/(sa[0]*sb[0]);
}
}

extern "C" double *mn_gaussian_f64(const double *values,int width,int height,double sigma) {
    try { cv::Mat output;cv::GaussianBlur(cv::Mat(height,width,CV_64F,const_cast<double *>(values)),output,cv::Size(),sigma);
        auto *result=(double *)malloc(size_t(width)*height*sizeof(double));if(result)memcpy(result,output.ptr<double>(),size_t(width)*height*sizeof(double));return result;
    }catch(...){return nullptr;}
}
extern "C" int mn_ellipse_outline(const double *points,int count,double *output,double center[2]) {
    try {
        if(count<6)return 0;bool closed=hypot(points[0]-points[2*(count-1)],points[1]-points[2*(count-1)+1])<1e-6;int n=count-(closed?1:0);cv::Point2d origin;
        for(int i=0;i<n;++i)origin+=cv::Point2d(points[i*2],points[i*2+1]);origin*=1./n;std::vector<cv::Point2f> samples;
        for(int i=0;i<n;++i)samples.emplace_back((float)(points[2*i]-origin.x),(float)(points[2*i+1]-origin.y));auto fit=cv::fitEllipse(samples);
        double rx=fit.size.width/2.,ry=fit.size.height/2.,angle=fit.angle*CV_PI/180,c=cos(angle),s=sin(angle);if(rx<=1e-6||ry<=1e-6)return 0;
        center[0]=origin.x+fit.center.x;center[1]=origin.y+fit.center.y;
        for(int i=0;i<count;++i){double x=points[i*2]-center[0],y=points[i*2+1]-center[1],phase=atan2((-s*x+c*y)/ry,(c*x+s*y)/rx);x=cos(phase)*rx;y=sin(phase)*ry;output[i*2]=center[0]+c*x-s*y;output[i*2+1]=center[1]+s*x+c*y;}
        if(closed){output[2*(count-1)]=output[0];output[2*(count-1)+1]=output[1];}return 1;
    }catch(...){return 0;}
}

extern "C" int mn_match(const uint8_t *reference,int rw,int rh,int rc,const uint8_t *photo,int pw,int ph,int pc,
                         const uint8_t *photoMask,double ratio,double contrast,double fraction,MNTask *task,MNMatch *result,char error[1024]) {
    memset(result,0,sizeof(*result));
    try {
        check(task);cv::setRNGSeed(0);double rs,ps;auto ref=enhanced(reference,rw,rh,rc,rs),image=enhanced(photo,pw,ph,pc,ps);
        auto sift=cv::SIFT::create(10000,3,contrast);
        cv::Mat mask;
        if(photoMask) {cv::resize(cv::Mat(ph,pw,CV_8U,const_cast<uint8_t *>(photoMask)),mask,image.size(),0,0,cv::INTER_NEAREST);cv::erode(mask,mask,cv::Mat::ones(7,7,CV_8U));}
        std::vector<cv::KeyPoint> pk;cv::Mat pd;sift->detectAndCompute(image,mask,pk,pd);
        if(pd.empty()||pk.size()<12)throw std::runtime_error("照片细节不足，自动配准失败。请使用手动地形参考点。");
        int bestCount=0;double bestCoverage=0;cv::Mat bestMatrix;
        std::vector<cv::Point2d> bestSource,bestTarget,bestAllSource,bestAllTarget;int bestMatches=0;bool bestMirror=false;double bestRMS=0;
        for(bool mirror:{false,true}) {
            check(task);cv::Mat current=ref;if(mirror)cv::flip(ref,current,1);
            std::vector<cv::KeyPoint> rk;cv::Mat rd;sift->detectAndCompute(current,cv::noArray(),rk,rd);if(rd.empty())continue;
            cv::BFMatcher matcher(cv::NORM_L2);std::vector<std::vector<cv::DMatch>> forward,reverse;
            matcher.knnMatch(rd,pd,forward,2);matcher.knnMatch(pd,rd,reverse,2);
            std::vector<int> backwards(pk.size(),-1);
            for(const auto &pair:reverse)if(pair.size()==2&&pair[0].distance<ratio*pair[1].distance)backwards[pair[0].queryIdx]=pair[0].trainIdx;
            std::vector<cv::Point2f> src,dst;
            for(const auto &pair:forward)if(pair.size()==2&&pair[0].distance<ratio*pair[1].distance&&backwards[pair[0].trainIdx]==pair[0].queryIdx) {
                src.push_back(rk[pair[0].queryIdx].pt);dst.push_back(pk[pair[0].trainIdx].pt);
            }
            if(src.size()<12)continue;
            cv::Mat inliers;auto m=cv::estimateAffinePartial2D(src,dst,inliers,cv::RANSAC,3,10000,.999);
            if(m.empty())continue;int count=cv::countNonZero(inliers);
            if(count<12||double(count)/src.size()<fraction)continue;
            std::vector<cv::Point2f> domain;std::vector<cv::Point2d> source,target,allSource,allTarget;double rms=0;
            for(size_t i=0;i<src.size();++i) {
                cv::Point2d p=src[i];if(mirror)p.x=ref.cols-1-p.x;p*=1/rs;
                allSource.push_back(p);allTarget.emplace_back(dst[i].x/ps,dst[i].y/ps);
                if(inliers.at<uint8_t>((int)i)) {domain.push_back(dst[i]);source.push_back(p);target.push_back(allTarget.back());auto d=transform(m,src[i])-cv::Point2d(dst[i]);rms+=d.dot(d);}
            }
            double coverage=hullArea(domain)/image.total();rms=sqrt(rms/count)/ps;
            if(coverage<.015||rms>4/ps)continue;
            if(count<bestCount||(count==bestCount&&coverage<=bestCoverage))continue;
            if(mirror){m.at<double>(0,2)+=m.at<double>(0,0)*(ref.cols-1);m.at<double>(1,2)+=m.at<double>(1,0)*(ref.cols-1);m.col(0)*=-1;}
            for(int row=0;row<2;++row){m.at<double>(row,0)*=rs/ps;m.at<double>(row,1)*=rs/ps;m.at<double>(row,2)/=ps;}
            bestMatrix=m;bestCount=count;bestCoverage=coverage;bestMatches=(int)src.size();bestMirror=mirror;bestRMS=rms;
            bestSource=std::move(source);bestTarget=std::move(target);bestAllSource=std::move(allSource);bestAllTarget=std::move(allTarget);
        }
        check(task);if(bestMatrix.empty())throw std::runtime_error("没有足够可靠的匹配。请核对拍摄时间，或用至少三处已知地形手动配准。");
        result->source=copyPoints(bestSource);result->target=copyPoints(bestTarget);result->source_matches=copyPoints(bestAllSource);result->target_matches=copyPoints(bestAllTarget);
        memcpy(result->matrix,bestMatrix.ptr<double>(),6*sizeof(double));result->count=bestCount;result->matches=bestMatches;result->mirrored=bestMirror;result->coverage=bestCoverage;result->rms=bestRMS;return 1;
    }catch(const std::exception &e){mn_match_destroy(result);problem(error,e);return 0;}
}

extern "C" int mn_realign_match(const uint8_t *reference,int rw,int rh,int rc,const uint8_t *photo,int pw,int ph,int pc,
                                 const uint8_t *mask,const double coarse[6],MNTask *task,MNMatch *result,char error[1024]) {
    memset(result,0,sizeof(*result));MNMatch fresh{};
    try {
        check(task);
        if(std::abs(coarse[0]*coarse[4]-coarse[1]*coarse[3])<1e-12)throw std::runtime_error("Invalid coarse registration");
        double factor=std::min(1.,2200./std::max(pw,ph));cv::Mat alignment=affine(coarse)*factor;
        cv::Mat source(rh,rw,CV_MAKETYPE(CV_8U,rc),const_cast<uint8_t *>(reference)),aligned;
        // Re-extract after moving the reference into the photo's sampling grid.
        // The original photograph and its mask remain unchanged.
        cv::warpAffine(source,aligned,alignment,{cvRound(pw*factor),cvRound(ph*factor)});
        if(!mn_match(aligned.ptr<uint8_t>(),aligned.cols,aligned.rows,rc,photo,pw,ph,pc,mask,.75,.02,.35,task,&fresh,error))return 0;
        cv::Mat inverse;cv::invertAffineTransform(alignment,inverse);
        auto restore=[&](double *points,int count){for(int i=0;i<count;++i){auto p=transform(inverse,{points[2*i],points[2*i+1]});points[2*i]=p.x;points[2*i+1]=p.y;}};
        restore(fresh.source,fresh.count);restore(fresh.source_matches,fresh.matches);
        cv::Mat homogeneous=cv::Mat::eye(3,3,CV_64F);alignment.copyTo(homogeneous.rowRange(0,2));
        cv::Mat composed=affine(fresh.matrix)*homogeneous;memcpy(fresh.matrix,composed.ptr<double>(),6*sizeof(double));
        fresh.mirrored=fresh.matrix[0]*fresh.matrix[4]-fresh.matrix[1]*fresh.matrix[3]<0;
        *result=fresh;return 1;
    }catch(const std::exception &e){mn_match_destroy(&fresh);problem(error,e);return 0;}
}
extern "C" void mn_match_destroy(MNMatch *result) {
    free(result->source);free(result->target);free(result->source_matches);free(result->target_matches);free(result->feature_indices);free(result->candidate_indices);memset(result,0,sizeof(*result));
}

extern "C" int mn_local_matches(const uint8_t *reference,const uint8_t *photo,int width,int height,const uint8_t *photoMask,MNTask *task,MNMatch *result,char error[1024]) {
    memset(result,0,sizeof(*result));
    try {
        check(task);double rs,ps;auto ref=enhanced(reference,width,height,4,rs),image=enhanced(photo,width,height,4,ps);cv::Mat refMask(image.size(),CV_8U,cv::Scalar(255)),mask;
        refMask.rowRange((int)round(ref.rows*.93),ref.rows).setTo(0);mask=refMask.clone();if(photoMask)mask&=cv::Mat(height,width,CV_8U,const_cast<uint8_t *>(photoMask));
        auto sift=cv::SIFT::create(10000,3,.01);std::vector<cv::KeyPoint> rk,pk;cv::Mat rd,pd;sift->detectAndCompute(ref,refMask,rk,rd);sift->detectAndCompute(image,mask,pk,pd);
        if(rd.empty()||pd.empty())return 0;cv::BFMatcher matcher(cv::NORM_L2);std::vector<std::vector<cv::DMatch>> forward,reverse;matcher.knnMatch(rd,pd,forward,2);matcher.knnMatch(pd,rd,reverse,2);
        std::vector<int> backwards(pk.size(),-1);for(auto pair:reverse)if(pair.size()==2&&pair[0].distance<.85*pair[1].distance)backwards[pair[0].queryIdx]=pair[0].trainIdx;
        std::vector<cv::Point2f> source,target;for(auto pair:forward)if(pair.size()==2&&pair[0].distance<.85*pair[1].distance&&backwards[pair[0].trainIdx]==pair[0].queryIdx){auto s=rk[pair[0].queryIdx].pt,t=pk[pair[0].trainIdx].pt;if(cv::norm(s-t)<25){source.push_back(s);target.push_back(t);}}
        if(source.size()<40)return 0;cv::setRNGSeed(0);cv::Mat inliers;cv::estimateAffinePartial2D(source,target,inliers,cv::RANSAC,5,10000,.999);if(inliers.empty())return 0;
        std::map<std::pair<int,int>,int> unique;for(size_t i=0;i<source.size();++i)if(inliers.at<uint8_t>(i)){std::pair<int,int> key{(int)nearbyint(source[i].x/4),(int)nearbyint(source[i].y/4)};unique.emplace(key,(int)i);}
        std::vector<cv::Point2d> s,t;std::vector<cv::Point2f> domain;for(auto pair:unique){s.emplace_back(source[pair.second]);t.emplace_back(target[pair.second]);domain.push_back(target[pair.second]);}
        if(s.size()<40)return 0;result->source=copyPoints(s);result->target=copyPoints(t);result->count=(int)s.size();result->matches=(int)source.size();result->coverage=hullArea(domain)/(double(width)*height);result->matrix[0]=1;result->matrix[4]=1;return 1;
    }catch(const std::exception &e){mn_match_destroy(result);problem(error,e);return 0;}
}

extern "C" int mn_reference_disk(const uint8_t *rgba,int width,int height,double result[3],char error[1024]) {
    try {
        cv::Mat alpha;cv::extractChannel(cv::Mat(height,width,CV_8UC4,const_cast<uint8_t *>(rgba)),alpha,3);
        double low,high;cv::minMaxLoc(alpha,&low,&high);if(low==high)throw std::runtime_error("参考图没有透明月盘边界，无法可靠确定尺度。请使用已校准参考工程。");
        std::vector<std::vector<cv::Point>> contours;cv::findContours(alpha>128,contours,cv::RETR_EXTERNAL,cv::CHAIN_APPROX_NONE);
        if(contours.empty())throw std::runtime_error("参考图没有完整月盘。");
        auto points=*std::max_element(contours.begin(),contours.end(),[](auto &a,auto &b){return cv::contourArea(a)<cv::contourArea(b);});
        cv::Mat design((int)points.size(),3,CV_64F),target((int)points.size(),1,CV_64F),solution;
        for(size_t i=0;i<points.size();++i){auto p=cv::Point2d(points[i]);design.at<double>(i,0)=2*p.x;design.at<double>(i,1)=2*p.y;design.at<double>(i,2)=1;target.at<double>(i)=p.dot(p);}
        cv::solve(design,target,solution,cv::DECOMP_SVD);cv::Point2d center(solution.at<double>(0),solution.at<double>(1));double radius=sqrt(std::max(0.,solution.at<double>(2)+center.dot(center)));
        std::vector<double> distances;for(auto p:points)distances.push_back(cv::norm(cv::Point2d(p)-center));cv::Scalar mean,deviation;cv::meanStdDev(distances,mean,deviation);
        if(radius<50||deviation[0]>1.5||cv::contourArea(points)<.9*CV_PI*radius*radius)throw std::runtime_error("参考图月盘轮廓不完整。请使用已校准参考工程。");
        result[0]=center.x;result[1]=center.y;result[2]=radius;return 1;
    }catch(const std::exception &e){problem(error,e);return 0;}
}

extern "C" int mn_limb(const uint8_t *pixels,int width,int height,int channels,const uint8_t *photoMask,MNTask *task,double result[5],char error[1024]) {
    try {
        auto original=gray(pixels,width,height,channels);double factor=std::min(1.,800./std::max(width,height));cv::Mat small;
        cv::resize(original,small,cv::Size(),factor,factor,cv::INTER_AREA);
        std::vector<uint8_t> histogram(small.datastart,small.dataend);auto q=histogram.begin()+(histogram.size()-1)*99/100;std::nth_element(histogram.begin(),q,histogram.end());
        cv::Mat mask;cv::compare(small,std::max(4.,*q*.12),mask,cv::CMP_GT);
        std::vector<std::vector<cv::Point>> contours;cv::findContours(mask,contours,cv::RETR_EXTERNAL,cv::CHAIN_APPROX_NONE);
        if(contours.empty())throw std::runtime_error("没有可用的月盘轮廓。");
        auto contour=*std::max_element(contours.begin(),contours.end(),[](const auto &a,const auto &b){return cv::contourArea(a)<cv::contourArea(b);});
        if(cv::contourArea(contour)<small.total()*.02||contour.size()<60)throw std::runtime_error("月盘轮廓太小，无法独立验证。");
        std::vector<cv::Point2d> points;
        for(size_t i=0;i<contour.size();i+=std::max<size_t>(1,contour.size()/700)) {
            auto p=contour[i];int px=std::clamp((int)round(p.x/factor),0,width-1),py=std::clamp((int)round(p.y/factor),0,height-1);
            if(!photoMask||photoMask[py*width+px])points.emplace_back(p);
        }
        if(points.size()<60)throw std::runtime_error("月盘外缘弧度不足；局部月缘不能仅靠轮廓定位。");
        std::mt19937 rng(17);std::vector<int> best;
        for(int iteration=0;iteration<3500;++iteration) {
            if(iteration%64==0)check(task);
            size_t i=rng()%points.size(),j=rng()%points.size(),k=rng()%points.size();if(i==j||j==k||i==k)continue;
            auto p=points[i],a=points[j],b=points[k];cv::Matx22d design(2*(a.x-p.x),2*(a.y-p.y),2*(b.x-p.x),2*(b.y-p.y));
            if(std::abs(cv::determinant(design))<50)continue;
            cv::Vec2d c=design.inv()*cv::Vec2d(a.dot(a)-p.dot(p),b.dot(b)-p.dot(p));cv::Point2d center(c[0],c[1]);double radius=cv::norm(center-p);
            if(radius<=.2*small.cols||radius>=1.1*small.cols||center.x<=-.1*small.cols||center.x>=1.1*small.cols||center.y<=-.1*small.rows||center.y>=2*small.rows)continue;
            std::vector<int> inliers;for(size_t n=0;n<points.size();++n)if(std::abs(cv::norm(points[n]-center)-radius)<1.5)inliers.push_back((int)n);
            if(inliers.size()>best.size())best=std::move(inliers);
        }
        if(best.size()<std::max(60.,points.size()*.25))throw std::runtime_error("月盘外缘弧度不足；局部月缘不能仅靠轮廓定位。");
        cv::Mat design((int)best.size(),3,CV_64F),targets((int)best.size(),1,CV_64F),solution;
        for(size_t n=0;n<best.size();++n){auto p=points[best[n]];design.at<double>(n,0)=2*p.x;design.at<double>(n,1)=2*p.y;design.at<double>(n,2)=1;targets.at<double>(n)=p.dot(p);}
        cv::solve(design,targets,solution,cv::DECOMP_SVD);cv::Point2d center(solution.at<double>(0),solution.at<double>(1));double radius=sqrt(std::max(0.,solution.at<double>(2)+center.dot(center)));
        std::vector<double> angles;double sum=0;
        for(int n:best){auto d=points[n]-center;angles.push_back(atan2(d.y,d.x));double e=cv::norm(d)-radius;sum+=e*e;}
        std::sort(angles.begin(),angles.end());double gap=angles.front()+2*M_PI-angles.back();for(size_t n=1;n<angles.size();++n)gap=std::max(gap,angles[n]-angles[n-1]);
        double rms=sqrt(sum/best.size());if(2*M_PI-gap<120*M_PI/180||rms>radius*.004)throw std::runtime_error("月盘外缘过短或偏离圆形，未采用轮廓配准。");
        result[0]=center.x/factor;result[1]=center.y/factor;result[2]=radius/factor;result[3]=rms/factor;result[4]=best.size();return 1;
    }catch(const std::exception &e){problem(error,e);return 0;}
}

extern "C" MNCandidate *mn_detect(const uint8_t *photo,int width,int height,int channels,const uint8_t *photoMask,
                                   double minimum,double maximum,int maxCount,double sensitivity,MNTask *task,int *count,char error[1024]) {
    *count=0;
    try {
        if(minimum<3||maximum<=minimum||maxCount<1||maxCount>500)throw std::runtime_error("检测半径或数量无效。");
        cv::Mat original=gray(photo,width,height,channels),image;double dimension=std::min(1600.,std::max(600.,std::max(width,height)*24/minimum));
        double factor=std::min(1.,dimension/std::max(width,height));cv::resize(original,image,cv::Size(),factor,factor,cv::INTER_AREA);
        double sx=double(image.cols)/width,sy=double(image.rows)/height;factor=std::min(sx,sy);sensitivity=std::clamp(sensitivity/100,0.,1.);
        cv::Mat background,hp,equalized,blur,enhanced;cv::GaussianBlur(image,background,cv::Size(),32);cv::addWeighted(image,1,background,-1,128,hp);
        cv::createCLAHE(2,{8,8})->apply(hp,equalized);cv::GaussianBlur(equalized,blur,cv::Size(),1);cv::addWeighted(equalized,1.4,blur,-.4,0,enhanced);cv::GaussianBlur(enhanced,enhanced,{5,5},1);
        std::vector<uint8_t> values(enhanced.datastart,enhanced.dataend);auto middle=values.begin()+values.size()/2;std::nth_element(values.begin(),middle,values.end());
        double lower=std::max(12.,(.75-.45*sensitivity)*(*middle)),upper=std::max(lower+20,(1.7-.5*sensitivity)*(*middle));
        cv::Mat edges,closed,mask;cv::Canny(enhanced,edges,lower,std::min(255.,upper));
        if(photoMask){cv::resize(cv::Mat(height,width,CV_8U,const_cast<uint8_t *>(photoMask)),mask,image.size(),0,0,cv::INTER_NEAREST);cv::erode(mask,mask,cv::Mat::ones(7,7,CV_8U));edges.setTo(0,mask==0);}
        cv::morphologyEx(edges,closed,cv::MORPH_CLOSE,cv::getStructuringElement(cv::MORPH_ELLIPSE,{5,5}));
        cv::Mat distance,labels,gx,gy;cv::distanceTransform(255-edges,distance,labels,cv::DIST_L2,3,cv::DIST_LABEL_PIXEL);cv::Sobel(enhanced,gx,CV_32F,1,0,3);cv::Sobel(enhanced,gy,CV_32F,0,1,3);
        double maxLabel;cv::minMaxLoc(labels,nullptr,&maxLabel);std::vector<cv::Point2f> gradients(size_t(maxLabel)+1);
        for(int y=0;y<edges.rows;++y)for(int x=0;x<edges.cols;++x)if(edges.at<uint8_t>(y,x)){cv::Point2f v(gx.at<float>(y,x),gy.at<float>(y,x));v*=1/std::max(1e-6,cv::norm(v));gradients[labels.at<int>(y,x)]=v;}
        // The largest closed photographic surface excludes detached captions while retaining dark crater floors.
        cv::Mat surface;cv::compare(image,4,surface,cv::CMP_GT);std::vector<std::vector<cv::Point>> footprint;
        cv::findContours(surface,footprint,cv::RETR_EXTERNAL,cv::CHAIN_APPROX_SIMPLE);surface.setTo(0);
        if(!footprint.empty()){int main=int(std::max_element(footprint.begin(),footprint.end(),[](const auto &a,const auto &b){return cv::contourArea(a)<cv::contourArea(b);})-footprint.begin());cv::drawContours(surface,footprint,main,cv::Scalar(255),cv::FILLED);}
        std::vector<MNCandidate> proposals;
        auto accept=[&](double cx,double cy,double a,double b,double angle,int method){
            if(b>a){std::swap(a,b);angle+=90;}double radius=(a+b)/2,theta=angle*M_PI/180,ct=cos(theta),st=sin(theta);
            if(radius<minimum*factor||radius>maximum*factor||b/a<.28)return;
            double hw=hypot(a*ct,b*st),hh=hypot(a*st,b*ct);if(cx-hw<2||cy-hh<2||cx+hw>=image.cols-2||cy+hh>=image.rows-2)return;
            int supported=0,sectors[8]={},surround=0;double tolerance=std::min(2.,std::max(1.,b*.12));
            for(int i=0;i<96;++i){double t=2*M_PI*i/96,dx=a*cos(t)*ct-b*sin(t)*st,dy=a*cos(t)*st+b*sin(t)*ct;int x=(int)round(cx+dx),y=(int)round(cy+dy);
                cv::Point2f normal(cos(t)/a*ct-sin(t)/b*st,cos(t)/a*st+sin(t)/b*ct);normal*=1/cv::norm(normal);
                bool good=distance.at<float>(y,x)<=tolerance&&std::abs(normal.dot(gradients[labels.at<int>(y,x)]))>.85&&(!photoMask||mask.at<uint8_t>(y,x));
                if(good){++supported;++sectors[i/12];}
                int ox=(int)round(cx+dx*1.3),oy=(int)round(cy+dy*1.3);if(ox>=0&&oy>=0&&ox<image.cols&&oy<image.rows&&surface.at<uint8_t>(oy,ox))++surround;
            }
            double support=supported/96.;if(support<.58-.16*sensitivity||std::count_if(sectors,sectors+8,[](int n){return n>=5;})<6||surround<60)return;
            if(radius>=std::min(image.cols,image.rows)*.2&&support<.55)return;
            cv::Matx22d basis(ct*a/sx,-st*b/sx,st*a/sy,ct*b/sy);cv::Mat singular,u,vt;cv::SVD::compute(cv::Mat(basis),singular,u,vt);
            proposals.push_back({cx/sx,cy/sy,singular.at<double>(0),singular.at<double>(1),fmod(atan2(u.at<double>(1,0),u.at<double>(0,0))*180/M_PI+180,180),support,support,support,method});
        };
        std::vector<std::vector<cv::Point>> contours;cv::findContours(closed,contours,cv::RETR_LIST,cv::CHAIN_APPROX_NONE);
        for(const auto &contour:contours){check(task);if(contour.size()<12)continue;auto ellipse=cv::fitEllipse(contour);double a=ellipse.size.width/2,b=ellipse.size.height/2;if(a<=0||b<=0)continue;
            double theta=ellipse.angle*M_PI/180;std::vector<double> errors;for(auto p:contour){double dx=p.x-ellipse.center.x,dy=p.y-ellipse.center.y,u=dx*cos(theta)+dy*sin(theta),v=-dx*sin(theta)+dy*cos(theta);errors.push_back(std::abs(hypot(u/a,v/b)-1));}
            auto mid=errors.begin()+errors.size()/2;std::nth_element(errors.begin(),mid,errors.end());if(*mid<=.09+.08*sensitivity)accept(ellipse.center.x,ellipse.center.y,a,b,ellipse.angle,0);
        }
        check(task);auto drawing=cv::ximgproc::createEdgeDrawing();drawing->detectEdges(enhanced);std::vector<cv::Vec6d> ellipses;drawing->detectEllipses(ellipses);
        for(auto e:ellipses) {double a=e[2]>0?e[2]:e[3],b=e[2]>0?e[2]:e[4];accept(e[0],e[1],a,b,e[5],2);}
        std::vector<cv::Vec3f> circles;int low=std::max(3,(int)floor(minimum*factor)),high=(int)ceil(std::min(maximum*factor,std::min(image.cols,image.rows)/2.));
        if(high>low)cv::HoughCircles(enhanced,circles,cv::HOUGH_GRADIENT,1.5,std::max(8.,low*1.5),120,45-20*sensitivity,low,high);
        for(auto c:circles)accept(c[0],c[1],c[2],c[2],0,1);
        std::sort(proposals.begin(),proposals.end(),[](const auto &a,const auto &b){return a.score>b.score;});std::vector<MNCandidate> selected;
        for(auto candidate:proposals){bool duplicate=false;for(auto prior:selected)if(hypot(candidate.x-prior.x,candidate.y-prior.y)<.45*std::min(candidate.major,prior.major)&&std::abs(candidate.major-prior.major)<.4*prior.major){duplicate=true;break;}if(!duplicate)selected.push_back(candidate);if((int)selected.size()>=maxCount)break;}
        auto *result=static_cast<MNCandidate *>(malloc(selected.size()*sizeof(MNCandidate)));if(!result&&!selected.empty())throw std::bad_alloc();memcpy(result,selected.data(),selected.size()*sizeof(MNCandidate));*count=(int)selected.size();return result;
    }catch(const std::exception &e){problem(error,e);return nullptr;}
}

extern "C" MNCandidate *mn_detect_rims(const uint8_t *photo,int width,int height,int channels,const uint8_t *photoMask,MNTask *task,int *count,char error[1024]) {
    *count=0;
    try {
        auto image=gray(photo,width,height,channels);if(std::min(width,height)<64)return nullptr;
        double sf=std::min(1.,800./std::max(width,height));cv::Mat small;cv::resize(image,small,cv::Size(),sf,sf,cv::INTER_AREA);
        std::vector<uint8_t> values;for(int y=0;y<small.rows;++y)for(int x=0;x<small.cols;++x){int px=std::min(width-1,(int)(x/sf)),py=std::min(height-1,(int)(y/sf));if(!photoMask||photoMask[py*width+px])values.push_back(small.at<uint8_t>(y,x));}
        if(values.empty())return nullptr;auto high=values.begin()+(values.size()-1)*99/100;std::nth_element(values.begin(),high,values.end());cv::Mat surface;cv::compare(small,std::max(4.,*high*.08),surface,cv::CMP_GT);
        int kernel=std::max(3,(int)round(std::max(small.cols,small.rows)/180.)|1);cv::morphologyEx(surface,surface,cv::MORPH_CLOSE,cv::Mat::ones(kernel,kernel,CV_8U));
        std::vector<std::vector<cv::Point>> contours;cv::findContours(surface,contours,cv::RETR_EXTERNAL,cv::CHAIN_APPROX_SIMPLE);surface.setTo(0);
        if(!contours.empty()){int main=int(std::max_element(contours.begin(),contours.end(),[](auto &a,auto &b){return cv::contourArea(a)<cv::contourArea(b);})-contours.begin());cv::drawContours(surface,contours,main,cv::Scalar(255),cv::FILLED);}
        int bottom=height;std::vector<double> dark(height);for(int y=0;y<height;++y){int n=0;for(int x=0;x<width;++x)n+=image.at<uint8_t>(y,x)<15;dark[y]=double(n)/width;}
        for(int y=int(height*.9);y<height-2;++y)if(std::min({dark[y],dark[y+1],dark[y+2]})>.9&&std::max({dark[y-1],dark[y-2],dark[y-3]})<.3){bottom=y;break;}
        std::vector<MNCandidate> proposals,kept;std::set<std::array<double,3>> passes;
        for(auto pass:std::vector<std::array<double,3>>{{1600,1,20},{1600,2,12},{1000,1,15},{2400,1,20}}){check(task);double factor=std::min(1.,pass[0]/std::max(width,height));if(!passes.insert({factor,pass[1],pass[2]}).second)continue;
            cv::Mat sample;cv::resize(image,sample,cv::Size(),factor,factor,cv::INTER_AREA);double sx=double(sample.cols)/width,sy=double(sample.rows)/height;
            auto detector=cv::ximgproc::createEdgeDrawing();detector->params.MinPathLength=20;detector->params.Sigma=(float)pass[1];detector->params.GradientThresholdValue=(int)pass[2];detector->params.NFAValidation=true;detector->detectEdges(sample);std::vector<cv::Vec6d> ellipses;detector->detectEllipses(ellipses);
            for(auto e:ellipses){double a=e[3]+e[2],b=e[4]+e[2],theta=e[5]*M_PI/180;if(std::min(a,b)<=0)continue;cv::Matx22d basis(cos(theta)*a/sx,-sin(theta)*b/sx,sin(theta)*a/sy,cos(theta)*b/sy);cv::Mat singular,u,vt;cv::SVD::compute(cv::Mat(basis),singular,u,vt);double major=singular.at<double>(0),minor=singular.at<double>(1),x=e[0]/sx,y=e[1]/sy;
                if(minor/major<.25||(major+minor)/2<8||major>std::min(width,height)*.3||x<0||y<0||x>=width||y>=bottom)continue;
                proposals.push_back({x,y,major,minor,std::remainder(atan2(u.at<double>(1,0),u.at<double>(0,0))*180/M_PI,180),1,1,1,2});
            }
        }
        for(auto c:proposals){check(task);double theta=c.angle*M_PI/180;int surrounding=0,available=0,maskOK=0;
            for(int i=0;i<64;++i){double t=2*M_PI*i/64,margin=std::max(3.,c.minor*.15),dx=(c.major+margin)*cos(t)*cos(theta)-(c.minor+margin)*sin(t)*sin(theta),dy=(c.major+margin)*cos(t)*sin(theta)+(c.minor+margin)*sin(t)*cos(theta);int x=int(round((c.x+dx)*surface.cols/width)),y=int(round((c.y+dy)*surface.rows/height));
                if(x>=0&&y>=0&&x<surface.cols&&y<surface.rows){++available;if(surface.at<uint8_t>(y,x))++surrounding;}
                int px=(int)round(c.x+dx),py=(int)round(c.y+dy);if(px>=0&&py>=0&&px<width&&py<height&&(!photoMask||photoMask[py*width+px]))++maskOK;
            }
            if(surrounding<64*.6||maskOK<48)continue;bool duplicate=false;for(auto other:kept)if(hypot(c.x-other.x,c.y-other.y)<.45*std::min(c.major,other.major)&&c.major/other.major>.5&&c.major/other.major<2){duplicate=true;break;}if(!duplicate)kept.push_back(c);
        }
        std::sort(kept.begin(),kept.end(),[](auto a,auto b){return a.major>b.major;});if(kept.size()>120)kept.resize(120);
        auto *result=(MNCandidate *)malloc(kept.size()*sizeof(MNCandidate));if(!result&&!kept.empty())throw std::bad_alloc();memcpy(result,kept.data(),kept.size()*sizeof(MNCandidate));*count=(int)kept.size();return result;
    }catch(const std::exception &e){problem(error,e);return nullptr;}
}

extern "C" int mn_dense_agreement(const uint8_t *reference,int rw,int rh,const uint8_t *photo,int pw,int ph,int channels,const double matrix[6],const uint8_t *photoMask,double result[2],char error[1024]) {
    try {
        auto image=gray(photo,pw,ph,channels);cv::Mat ref(rh,rw,CV_8U,const_cast<uint8_t *>(reference)),projected,available;
        cv::warpAffine(ref,projected,affine(matrix),{pw,ph});cv::warpAffine(cv::Mat(rh,rw,CV_8U,cv::Scalar(255)),available,affine(matrix),{pw,ph});
        cv::Mat foreground,domain=cv::Mat::zeros(ph,pw,CV_8U);cv::compare(image,15,foreground,cv::CMP_GT);int kernel=std::max(3,(int)round(std::max(pw,ph)/180.)|1);cv::morphologyEx(foreground,foreground,cv::MORPH_CLOSE,cv::Mat::ones(kernel,kernel,CV_8U));
        std::vector<std::vector<cv::Point>> contours;cv::findContours(foreground,contours,cv::RETR_EXTERNAL,cv::CHAIN_APPROX_SIMPLE);foreground.setTo(0);
        if(!contours.empty()){auto main=*std::max_element(contours.begin(),contours.end(),[](const auto &a,const auto &b){return cv::contourArea(a)<cv::contourArea(b);});std::vector<cv::Point> hull;cv::convexHull(main,hull);cv::fillConvexPoly(foreground,hull,cv::Scalar(255));}
        for(int y=(int)round(ph*.08);y<(int)round(ph*.93);++y)for(int x=(int)round(pw*.05);x<(int)round(pw*.95);++x)if(available.at<uint8_t>(y,x)>250&&foreground.at<uint8_t>(y,x)&&(image.at<uint8_t>(y,x)>15||projected.at<uint8_t>(y,x)>15)&&(!photoMask||photoMask[y*pw+x]))domain.at<uint8_t>(y,x)=255;
        if(cv::countNonZero(domain)<600)throw std::runtime_error("高程参考有效纹理不足，未采用结果。");
        cv::Scalar mean,stdA,stdB;cv::meanStdDev(image,mean,stdA,domain);cv::meanStdDev(projected,mean,stdB,domain);if(std::min(stdA[0],stdB[0])<8)throw std::runtime_error("高程参考有效纹理不足，未采用结果。");
        result[0]=correlation(image,projected,domain);cv::Mat a,b,lowA,lowB;image.convertTo(a,CV_32F);projected.convertTo(b,CV_32F);double sigma=std::max(2.,std::max(pw,ph)/88.);cv::GaussianBlur(a,lowA,cv::Size(),sigma);cv::GaussianBlur(b,lowB,cv::Size(),sigma);a-=lowA;b-=lowB;
        cv::meanStdDev(a,mean,stdA,domain);cv::meanStdDev(b,mean,stdB,domain);if(std::min(stdA[0],stdB[0])<2)throw std::runtime_error("高程参考缺少独立地形细节。");result[1]=correlation(a,b,domain);return 1;
    }catch(const std::exception &e){problem(error,e);return 0;}
}

using moonoptics::ViewGeometry;
using moonoptics::opticalRadial;
using moonoptics::opticalPredict;
namespace {
std::vector<cv::Point2d> predict(const cv::Mat &p,const ViewGeometry &geometry,const cv::Mat &matrix,const std::vector<cv::Vec3d> &surface) {
    auto g=geometry.shifted(p.at<double>(0),p.at<double>(1));double c=cos(p.at<double>(3)),s=sin(p.at<double>(3)),scale=exp(p.at<double>(2));std::vector<cv::Point2d> result;
    for(auto v:surface){auto x=transform(matrix,g.project(v));result.emplace_back(scale*(c*x.x-s*x.y)+p.at<double>(4),scale*(s*x.x+c*x.y)+p.at<double>(5));}return result;
}
cv::Mat optimize(const ViewGeometry &g,const cv::Mat &matrix,const std::vector<cv::Vec3d> &surface,const std::vector<cv::Point2d> &target,bool freeView,double bound) {
    cv::Mat p=cv::Mat::zeros(6,1,CV_64F);int start=freeView?0:2,n=6-start;double damping=1e-4,steps[]={1e-4,1e-4,1e-5,1e-5,.001,.001};
    auto cost=[](double e){return e<3?e*e:6*e-9;};
    for(int iteration=0;iteration<60;++iteration){auto prediction=predict(p,g,matrix,surface);cv::Mat residual((int)surface.size()*2,1,CV_64F),jac((int)surface.size()*2,n,CV_64F),weights((int)surface.size()*2,1,CV_64F);double before=0;
        for(size_t i=0;i<surface.size();++i){auto d=prediction[i]-target[i];double e=cv::norm(d);before+=cost(e);residual.at<double>(2*i)=d.x;residual.at<double>(2*i+1)=d.y;weights.at<double>(2*i)=weights.at<double>(2*i+1)=std::min(1.,3/std::max(e,1e-8));}
        for(int j=start;j<6;++j){auto probe=p.clone();probe.at<double>(j)+=steps[j];auto shifted=predict(probe,g,matrix,surface);for(size_t i=0;i<surface.size();++i){auto d=(shifted[i]-prediction[i])/steps[j];jac.at<double>(2*i,j-start)=d.x;jac.at<double>(2*i+1,j-start)=d.y;}}
        cv::Mat weighted=jac.clone();for(int i=0;i<weighted.rows;++i)weighted.row(i)*=weights.at<double>(i);cv::Mat normal=jac.t()*weighted,rhs=jac.t()*(weights.mul(residual)),delta;
        for(int i=0;i<n;++i)normal.at<double>(i,i)+=damping*std::max(1e-8,normal.at<double>(i,i));if(!cv::solve(normal,rhs,delta,cv::DECOMP_CHOLESKY))return {};
        auto proposal=p.clone();for(int j=start;j<6;++j)proposal.at<double>(j)-=delta.at<double>(j-start);for(int i=0;i<2;++i)proposal.at<double>(i)=std::clamp(proposal.at<double>(i),-bound,bound);for(int i=2;i<4;++i)proposal.at<double>(i)=std::clamp(proposal.at<double>(i),-.1,.1);
        double after=0;auto next=predict(proposal,g,matrix,surface);for(size_t i=0;i<surface.size();++i)after+=cost(cv::norm(next[i]-target[i]));
        if(after<before){p=proposal;damping=std::max(damping/3,1e-8);if(cv::norm(delta)<1e-7)break;}else if((damping*=10)>1e12)break;
    }return p;
}
double rms(const std::vector<cv::Point2d> &a,const std::vector<cv::Point2d> &b){double sum=0;for(size_t i=0;i<a.size();++i){auto d=a[i]-b[i];sum+=d.dot(d);}return sqrt(sum/a.size());}
}
extern "C" uint8_t *mn_albedo_atlas(const uint8_t *texture,int width,int height,const double geometry[13],int size,MNTask *task,double *validFraction,char error[1024]) {
    try {
        if(!texture||width<=0||height<=0||size<1||size>8192)throw std::runtime_error("反照率参考图尺寸无效。");
        ViewGeometry g(geometry);cv::Mat input(height,width,CV_8UC4,const_cast<uint8_t *>(texture)),output(size,size,CV_8UC4,cv::Scalar(0,0,0,255));
        double scale=size*.47,center=(size-1)/2.,d=g.distance/1737.4;int valid=0;
        for(int first=0;first<size;first+=64){
            check(task);int rows=std::min(64,size-first);cv::Mat mx(rows,size,CV_32F,cv::Scalar(0)),my=mx.clone(),light(rows,size,CV_64F,cv::Scalar(0)),color;
            for(int row=0;row<rows;++row)for(int col=0;col<size;++col){
                cv::Point2d p((col-center)/scale,(first+row-center)/scale);auto ray=-g.observer+(p.x*g.right-p.y*g.north)/d;
                double a=ray.dot(ray),disc=d*d-a*(d*d-1);if(disc<0)continue;
                double length=(d*d-1)/(d+sqrt(disc));auto v=d*g.observer+length*ray;
                double lat=asin(std::clamp(v[2],-1.,1.)),lon=atan2(v[1],v[0]);
                cv::Vec3d radial(cos(lat)*cos(lon),cos(lat)*sin(lon),sin(lat));
                mx.at<float>(row,col)=(float)((lon+M_PI)/(2*M_PI)*width-.5);
                my.at<float>(row,col)=(float)((M_PI/2-lat)/M_PI*height-.5);
                double incidence=std::max(0.,radial.dot(g.sun)),emission=std::max(0.,radial.dot(g.observer));
                light.at<double>(row,col)=sqrt(std::clamp(2*incidence/(incidence+emission+1e-8),0.,1.));++valid;
            }
            // OpenCV rounds the bilinear sample to a byte before applying light,
            // as in Python's atlas. Continuous interpolation changes SIFT points.
            cv::remap(input,color,mx,my,cv::INTER_LINEAR,cv::BORDER_WRAP);
            for(int row=0;row<rows;++row)for(int col=0;col<size;++col){auto &pixel=output.at<cv::Vec4b>(first+row,col);auto sampled=color.at<cv::Vec4b>(row,col);for(int c=0;c<3;++c)pixel[c]=(uint8_t)(sampled[c]*light.at<double>(row,col));}
        }
        auto *result=(uint8_t *)malloc(output.total()*4);if(!result)throw std::bad_alloc();memcpy(result,output.data,output.total()*4);
        if(validFraction)*validFraction=double(valid)/(double(size)*size);return result;
    }catch(const std::exception &e){problem(error,e);return nullptr;}
}
extern "C" int mn_refine_view(const double geometry[13],const double original[6],const double *source,const double *target,const double *surfaceOverride,int count,int width,int height,double bound,int cameraOnly,double updatedGeometry[13],double updatedMatrix[6],double evidence[6],char error[1024]) {
    try {
        if(count<40)return 0;ViewGeometry g(geometry);auto matrix=affine(original);cv::Mat inverse;cv::invertAffineTransform(matrix,inverse);
        std::vector<cv::Vec3d> surface;std::vector<cv::Point2d> targets;std::vector<cv::Point2f> domain;std::vector<int> cells;
        for(int i=0;i<count;++i){cv::Point2d p(source[2*i],source[2*i+1]),t(target[2*i],target[2*i+1]);surface.push_back(surfaceOverride?cv::Vec3d(surfaceOverride[3*i],surfaceOverride[3*i+1],surfaceOverride[3*i+2]):g.unproject(transform(inverse,p)));targets.push_back(t);domain.emplace_back(t);cells.push_back(std::clamp(int(p.x/width*3),0,2)+3*std::clamp(int(p.y/height*3),0,2));}
        double coverage=hullArea(domain)/(double(width)*height);if(coverage<.18)return 0;
        auto fit=optimize(g,matrix,surface,targets,!cameraOnly,std::max(1.5,bound));if(fit.empty()||hypot(fit.at<double>(0),fit.at<double>(1))>bound)return 0;
        if(cameraOnly){if(std::abs(fit.at<double>(2))>.03||std::abs(fit.at<double>(3))>3*M_PI/180)return 0;auto predicted=predict(fit,g,matrix,surface);for(int i=0;i<count;++i)if(cv::norm(predicted[i]-cv::Point2d(source[2*i],source[2*i+1]))>std::min(width,height)*.04)return 0;}
        int folds=0,improved=0,total=0;double beforeSum=0,afterSum=0;
        for(int cell=0;cell<9;++cell){std::vector<cv::Vec3d> train,hold;std::vector<cv::Point2d> tt,ht;for(int i=0;i<count;++i)if(cells[i]==cell){hold.push_back(surface[i]);ht.push_back(targets[i]);}else{train.push_back(surface[i]);tt.push_back(targets[i]);}
            if(hold.size()<3||train.size()<20)continue;auto baseline=optimize(g,matrix,train,tt,false,1.5),candidate=optimize(g,matrix,train,tt,!cameraOnly,std::max(1.5,bound));
            if(baseline.empty()||candidate.empty()||hypot(candidate.at<double>(0)-fit.at<double>(0),candidate.at<double>(1)-fit.at<double>(1))>.35)return 0;
            double before;if(cameraOnly){std::vector<cv::Point2d> raw;for(int i=0;i<count;++i)if(cells[i]==cell)raw.emplace_back(source[2*i],source[2*i+1]);before=rms(raw,ht);}else before=rms(predict(baseline,g,matrix,hold),ht);
            double after=rms(predict(candidate,g,matrix,hold),ht);if(after>before*1.1+.25)return 0;
            ++folds;if(after<before)++improved;total+=(int)hold.size();beforeSum+=before*before*hold.size();afterSum+=after*after*hold.size();
        }
        if(folds<4||improved<.75*folds)return 0;double before=sqrt(beforeSum/total),after=sqrt(afterSum/total);if(after>before*.85||before-after<.25)return 0;
        auto shifted=g.shifted(fit.at<double>(0),fit.at<double>(1));shifted.store(updatedGeometry);double c=cos(fit.at<double>(3)),s=sin(fit.at<double>(3)),scale=exp(fit.at<double>(2));cv::Mat camera=(cv::Mat_<double>(2,2)<<scale*c,-scale*s,scale*s,scale*c);cv::Mat updated=camera*matrix;updated.at<double>(0,2)+=fit.at<double>(4);updated.at<double>(1,2)+=fit.at<double>(5);memcpy(updatedMatrix,updated.ptr<double>(),6*sizeof(double));
        evidence[0]=rms(predict(fit,g,matrix,surface),targets);evidence[1]=coverage;evidence[2]=before;evidence[3]=after;evidence[4]=fit.at<double>(0);evidence[5]=fit.at<double>(1);return 1;
    }catch(const std::exception &e){problem(error,e);return 0;}
}

namespace {
cv::Mat opticalFit(const cv::Mat &initial,const ViewGeometry &g,const std::vector<cv::Vec3d> &surface,const std::vector<cv::Point2d> &target,int sign,double scale,MNTask *task) {
    cv::Mat p=initial.clone();double damping=.001;auto loss=[](double e){return e<3?e*e:6*e-9;};
    for(int iteration=0;iteration<80;++iteration){check(task);auto predicted=opticalPredict(p,g,surface,sign);cv::Mat residual((int)surface.size()*2,1,CV_64F),jac((int)surface.size()*2,9,CV_64F),weights((int)surface.size()*2,1,CV_64F);double before=0;
        for(size_t i=0;i<surface.size();++i){auto d=predicted[i]-target[i];double e=cv::norm(d)*scale;before+=loss(e);residual.at<double>(2*i)=d.x;residual.at<double>(2*i+1)=d.y;weights.at<double>(2*i)=weights.at<double>(2*i+1)=std::min(1.,3/std::max(e,1e-8));}
        for(int j=0;j<9;++j){auto probe=p.clone();probe.at<double>(j)+=1e-5;auto shifted=opticalPredict(probe,g,surface,sign);for(size_t i=0;i<surface.size();++i){auto d=(shifted[i]-predicted[i])*1e5;jac.at<double>(2*i,j)=d.x;jac.at<double>(2*i+1,j)=d.y;}}
        cv::Mat weighted=jac.clone();for(int i=0;i<weighted.rows;++i)weighted.row(i)*=weights.at<double>(i);cv::Mat normal=jac.t()*weighted,rhs=jac.t()*(weights.mul(residual)),delta;
        for(int i=0;i<9;++i)normal.at<double>(i,i)+=damping*std::max(normal.at<double>(i,i),1e-8);if(!cv::solve(normal,rhs,delta,cv::DECOMP_CHOLESKY))return {};
        cv::Mat trial=p-delta;trial.at<double>(4)=std::clamp(trial.at<double>(4),0.,.6);for(int i=5;i<7;++i)trial.at<double>(i)=std::clamp(trial.at<double>(i),-.7,.7);for(int i=7;i<9;++i)trial.at<double>(i)=std::clamp(trial.at<double>(i),-1.25,1.25);
        double after=0;auto next=opticalPredict(trial,g,surface,sign);for(size_t i=0;i<surface.size();++i)after+=loss(cv::norm(next[i]-target[i])*scale);
        if(after<before){p=trial;damping=std::max(1e-8,damping/3);if(cv::norm(delta)<1e-7)break;}else if((damping*=10)>1e12)break;
    }return p;
}
double percentile(std::vector<double> values,double fraction){if(values.empty())return INFINITY;std::sort(values.begin(),values.end());double at=fraction*(values.size()-1);size_t i=(size_t)at;double f=at-i;return values[i]*(1-f)+values[std::min(i+1,values.size()-1)]*f;}
}
extern "C" int mn_eyepiece(const double geometry[13],const double projection[6],const double camera[6],const double *src,const double *dst,int count,int rigidInliers,double rigidCoverage,
                            const uint8_t *photo,int width,int height,int channels,const uint8_t *photoMask,const double *limb,MNTask *task,double updatedGeometry[13],double matrix[6],double distortion[4],double evidence[7],char error[1024]) {
    try {
        if(rigidInliers<64||count<100)throw std::runtime_error("目镜校正缺少可靠的纹理对应点。");
        ViewGeometry g(geometry);cv::Mat inverse;cv::invertAffineTransform(affine(projection),inverse);std::vector<cv::Vec3d> surface;std::vector<cv::Point2d> pixels;std::set<std::array<long,4>> seen;
        for(int i=0;i<count;++i){std::array<long,4> key{lround(src[2*i]*8),lround(src[2*i+1]*8),lround(dst[2*i]*8),lround(dst[2*i+1]*8)};if(!seen.insert(key).second)continue;try{surface.push_back(g.unproject(transform(inverse,{src[2*i],src[2*i+1]})));pixels.emplace_back(dst[2*i],dst[2*i+1]);}catch(...) {}}
        if(surface.size()>800){std::vector<cv::Vec3d> s;std::vector<cv::Point2d> p;for(int i=0;i<800;++i){size_t index=size_t(i*(surface.size()-1)/799);s.push_back(surface[index]);p.push_back(pixels[index]);}surface=std::move(s);pixels=std::move(p);}
        if(surface.size()<100)throw std::runtime_error("目镜校正需要至少 100 个分散的纹理对应点。");
        double area=double(width)*height,scale=std::max(width,height)/2.;cv::Point2d center(width/2.,height/2.);
        if(limb&&rigidCoverage<.08){area=std::min(area,4*limb[2]*limb[2]);scale=limb[2];center={limb[0],limb[1]};}
        int sign=camera[0]*camera[4]-camera[1]*camera[3]<0?-1:1;
        cv::Mat initial=(cv::Mat_<double>(9,1)<<camera[0]/sign/scale,camera[3]/sign/scale,(camera[2]-center.x)/scale,(camera[5]-center.y)/scale,.1,0,0,0,0);
        std::vector<cv::Point2d> target;for(auto p:pixels)target.push_back((p-center)/scale);auto params=opticalFit(initial,g,surface,target,sign,scale,task);
        if(params.empty()||params.at<double>(4)<=.015||params.at<double>(4)>=.55||hypot(params.at<double>(7),params.at<double>(8))>1.25)throw std::runtime_error("目镜校正参数未通过验证。");
        auto predicted=opticalPredict(params,g,surface,sign);std::vector<int> inliers;std::vector<cv::Point2f> occupied;double square=0;
        for(size_t i=0;i<target.size();++i){double e=cv::norm(predicted[i]-target[i])*scale;if(e<3){inliers.push_back((int)i);occupied.emplace_back(pixels[i]);square+=e*e;}}
        double coverage=hullArea(occupied)/area;if(inliers.size()<100||double(inliers.size())/surface.size()<.8||coverage<.08)throw std::runtime_error("目镜校正的纹理验证不足。");
        auto effective=g.shifted(params.at<double>(7),params.at<double>(8));auto image=gray(photo,width,height,channels);double factor=std::min(1.,1400./std::max(width,height));cv::Mat small;cv::resize(image,small,cv::Size(),factor,factor,cv::INTER_AREA);
        std::vector<uint8_t> intensities(small.datastart,small.dataend);auto high=intensities.begin()+(intensities.size()-1)*99/100;std::nth_element(intensities.begin(),high,intensities.end());cv::Mat bright;cv::compare(small,std::max(30.,*high*.25),bright,cv::CMP_GT);
        std::vector<std::vector<cv::Point>> contours;cv::findContours(bright,contours,cv::RETR_EXTERNAL,cv::CHAIN_APPROX_NONE);if(contours.empty())throw std::runtime_error("目镜校正缺少可验证的受光月缘。");
        int main=int(std::max_element(contours.begin(),contours.end(),[](const auto &a,const auto &b){return cv::contourArea(a)<cv::contourArea(b);})-contours.begin());if(cv::contourArea(contours[main])/(factor*factor)<area*.1)throw std::runtime_error("目镜校正需要较完整的月面视野。");
        cv::Mat boundary(small.size(),CV_8U,cv::Scalar(1)),distances;cv::drawContours(boundary,contours,main,cv::Scalar(0),1);cv::distanceTransform(boundary,distances,cv::DIST_L2,5);distances/=factor;
        std::vector<cv::Point2d> rim;std::vector<double> rimErrors;double margin=effective.observer.dot(effective.sun)>.98?.02:.15;
        for(int i=0;i<720;++i){double t=2*M_PI*i/720;cv::Point2d circle(cos(t),sin(t));auto radial=effective.unproject(circle*.999);if(radial.dot(effective.sun)<=margin)continue;auto point=opticalRadial(params,circle,sign)*scale+center;int x=(int)round(point.x*factor),y=(int)round(point.y*factor);
            if(point.x<=3||point.y<=3||point.x>=width-4||point.y>=height-4||x<0||y<0||x>=small.cols||y>=small.rows||(photoMask&&!photoMask[(int)point.y*width+(int)point.x]))continue;rim.push_back(circle);rimErrors.push_back(distances.at<float>(y,x));}
        if(rim.size()<240)throw std::runtime_error("目镜校正的可验证月缘不足 120°。");double tolerance=std::max(4/factor,scale*.008),p95=percentile(rimErrors,.95);
        if(p95>tolerance||percentile(rimErrors,.5)>tolerance*.7)throw std::runtime_error("目镜校正仍与实际受光月缘不一致。");
        auto grid=[&](bool useInliers){
            double minX=INFINITY,minY=INFINITY,maxX=-INFINITY,maxY=-INFINITY;
            auto include=[&](cv::Point2d p){minX=std::min(minX,p.x);maxX=std::max(maxX,p.x);minY=std::min(minY,p.y);maxY=std::max(maxY,p.y);};
            if(useInliers){for(int i:inliers)include(pixels[i]);}else{for(auto p:pixels)include(p);}
            std::vector<int> cells;for(auto p:pixels)cells.push_back(std::clamp(int((p.x-minX)/std::max(1.,maxX-minX)*3),0,2)+3*std::clamp(int((p.y-minY)/std::max(1.,maxY-minY)*3),0,2));return cells;
        };
        auto cells=grid(false);std::array<int,9> counts{};for(int cell:cells)++counts[cell];
        // Match Python: only shrink the validation grid when outliers leave
        // fewer than four populated regions. Every descriptor remains held out.
        if(std::count_if(counts.begin(),counts.end(),[](int count){return count>=10;})<4)cells=grid(true);
        int folds=0;for(int cell=0;cell<9;++cell){std::vector<cv::Vec3d> train,hold;std::vector<cv::Point2d> tt,ht;for(size_t i=0;i<surface.size();++i)if(cells[i]==cell){hold.push_back(surface[i]);ht.push_back(target[i]);}else{train.push_back(surface[i]);tt.push_back(target[i]);}if(hold.size()<10)continue;
            auto other=opticalFit(initial,g,train,tt,sign,scale,task);if(other.empty()||hypot(other.at<double>(7),other.at<double>(8))>1.25)throw std::runtime_error("目镜校正的分区验证失败。");auto checks=opticalPredict(other,g,hold,sign);int within=0;for(size_t i=0;i<hold.size();++i)if(cv::norm(checks[i]-ht[i])*scale<4)++within;
            std::vector<double> delta;for(auto p:rim)delta.push_back(cv::norm(opticalRadial(other,p,sign)-opticalRadial(params,p,sign))*scale);
            if(double(within)/hold.size()<.8||percentile(delta,.95)>std::max(3.,scale*.006))throw std::runtime_error("目镜校正的分区预测不稳定。");++folds;
        }
        if(folds<4)throw std::runtime_error("目镜校正缺少独立验证区域。");effective.store(updatedGeometry);double a=params.at<double>(0),b=params.at<double>(1);
        double m[]={a*sign*scale,-b*scale,params.at<double>(2)*scale+center.x,b*sign*scale,a*scale,params.at<double>(3)*scale+center.y};memcpy(matrix,m,sizeof(m));
        distortion[0]=center.x+scale*params.at<double>(5);distortion[1]=center.y+scale*params.at<double>(6);distortion[2]=scale;distortion[3]=params.at<double>(4);
        evidence[0]=sqrt(square/inliers.size());evidence[1]=inliers.size();evidence[2]=coverage;evidence[3]=p95;evidence[4]=rim.size()/2.;evidence[5]=params.at<double>(7);evidence[6]=params.at<double>(8);return 1;
    }catch(const std::exception &e){problem(error,e);return 0;}
}

extern "C" int mn_compact_field(const uint8_t *photo,int width,int height,int channels,const uint8_t *photoMask,int rectangle[4]) {
    try {
        double scale=std::min(1.,800./std::max(width,height));auto image=gray(photo,width,height,channels);cv::Mat small,foreground,labels,stats,centroids;
        cv::resize(image,small,cv::Size(),scale,scale,cv::INTER_AREA);cv::compare(small,30,foreground,cv::CMP_GT);
        if(photoMask){cv::Mat mask;cv::resize(cv::Mat(height,width,CV_8U,const_cast<uint8_t *>(photoMask)),mask,small.size(),0,0,cv::INTER_NEAREST);foreground.setTo(0,mask==0);}
        int count=cv::connectedComponentsWithStats(foreground,labels,stats,centroids);if(count<2)return 0;
        int main=1;for(int i=2;i<count;++i)if(stats.at<int>(i,cv::CC_STAT_AREA)>stats.at<int>(main,cv::CC_STAT_AREA))main=i;
        int x=stats.at<int>(main,0),y=stats.at<int>(main,1),w=stats.at<int>(main,2),h=stats.at<int>(main,3),area=stats.at<int>(main,4),total=cv::countNonZero(foreground);
        if(area<small.total()*.005||w*h>small.total()*.1||std::max(w,h)>.45*std::min(small.cols,small.rows)||double(w)/h<=.5||double(w)/h>=2||std::min(w,h)/scale<160||x<=1||y<=1||x+w>=small.cols-1||y+h>=small.rows-1)return 0;
        int removed=0;
        for(int i=1;i<count;++i)if(i!=main){int sx=stats.at<int>(i,0),sy=stats.at<int>(i,1),sw=stats.at<int>(i,2),sh=stats.at<int>(i,3),sa=stats.at<int>(i,4);bool border=sy+sh<small.rows*.15||sy>small.rows*.85||sx+sw<small.cols*.15||sx>small.cols*.85;
            if(border&&sa<.03*area&&sw<.3*std::min(w,h)&&sh<.3*std::min(w,h))removed+=sa;}
        if(removed<=.3*area)total-=removed;if(area<.95*total)return 0;
        double pad=.15*std::max(w,h);int left=std::max(0,(int)floor((x-pad)/scale)),top=std::max(0,(int)floor((y-pad)/scale));
        rectangle[0]=left;rectangle[1]=top;rectangle[2]=std::min(width,(int)ceil((x+w+pad)/scale))-left;rectangle[3]=std::min(height,(int)ceil((y+h+pad)/scale))-top;return 1;
    }catch(...){return 0;}
}

extern "C" int mn_limb_pose(const uint8_t *reference,int size,const uint8_t *photo,int width,int height,int channels,const uint8_t *photoMask,
                             const double geometry[13],const double limb[5],MNTask *task,double matrix[6],double evidence[2],char error[1024]) {
    try {
        auto ref=gray(reference,size,size,4),original=gray(photo,width,height,channels);cv::Mat a,low,high,photoFloat;ref.convertTo(a,CV_32F);cv::GaussianBlur(a,low,cv::Size(),8);high=a-low;
        original.convertTo(photoFloat,CV_32F);cv::GaussianBlur(photoFloat,photoFloat,cv::Size(),limb[2]/100);
        cv::Mat disk(size,size,CV_8U,cv::Scalar(0)),keep=disk.clone();for(int y=0;y<size;++y)for(int x=0;x<size;++x){double px=(x-(size-1)/2.)/(size*.47),py=(y-(size-1)/2.)/(size*.47);if(px*px+py*py<.81){disk.at<uint8_t>(y,x)=255;if(ref.at<uint8_t>(y,x)>20)keep.at<uint8_t>(y,x)=255;}}
        cv::Scalar mean,sd;cv::meanStdDev(high,mean,sd,keep);if(cv::countNonZero(keep)<500||sd[0]<2)throw std::runtime_error("月海纹理不足，月相轮廓本身不能确认方向。");
        double scale=limb[2]*sqrt(1-pow(1737.4/geometry[12],2));struct Score{double texture,phase,angle;int sign;};std::vector<Score> scores;
        auto compare=[&](double angle,int sign){check(task);double t=angle*M_PI/180,c=cos(t),s=sin(t);cv::Mat mx(size,size,CV_32F),my(size,size,CV_32F),domain=keep.clone(),phase=disk.clone();int available=0,required=cv::countNonZero(keep);
            for(int y=0;y<size;++y)for(int x=0;x<size;++x){double px=(x-(size-1)/2.)/(size*.47)*sign,py=(y-(size-1)/2.)/(size*.47),tx=scale*(c*px-s*py)+limb[0],ty=scale*(s*px+c*py)+limb[1];mx.at<float>(y,x)=(float)tx;my.at<float>(y,x)=(float)ty;
                bool inside=tx>=0&&ty>=0&&tx<width&&ty<height,allowed=inside&&(!photoMask||photoMask[(int)ty*width+(int)tx]);if(inside&&keep.at<uint8_t>(y,x))++available;if(!allowed){domain.at<uint8_t>(y,x)=0;phase.at<uint8_t>(y,x)=0;}}
            if(available<required*.8||cv::countNonZero(domain)<std::max(500.,required*.5)||cv::countNonZero(phase)<cv::countNonZero(disk)*.5)return Score{-1,-1,angle,sign};
            cv::Mat sample,hp,blur;cv::remap(photoFloat,sample,mx,my,cv::INTER_LINEAR,cv::BORDER_CONSTANT);cv::GaussianBlur(sample,blur,cv::Size(),8);hp=sample-blur;
            return Score{correlation(high,hp,domain),correlation(a,sample,phase),angle,sign};};
        for(int sign:{1,-1})for(int angle=0;angle<360;angle+=2)scores.push_back(compare(angle,sign));auto best=*std::max_element(scores.begin(),scores.end(),[](auto a,auto b){return a.texture<b.texture;});
        for(int i=-8;i<=8;++i)scores.push_back(compare(best.angle+i*.25,best.sign));best=*std::max_element(scores.begin(),scores.end(),[](auto a,auto b){return a.texture<b.texture;});
        double competing=-1;for(auto row:scores){double angle=std::abs(std::remainder(row.angle-best.angle,360.));if(row.sign!=best.sign||angle>=8)competing=std::max(competing,row.texture);}
        if(best.texture<.5||best.phase<.75)throw std::runtime_error("月盘轮廓已拟合，但月海纹理与月相未同时通过验证。");if(best.texture-competing<.15)throw std::runtime_error("月海纹理存在接近的方向或镜像，未采用配准。");
        double t=best.angle*M_PI/180,c=cos(t)*scale,s=sin(t)*scale;double m[]={c*best.sign,-s,limb[0],s*best.sign,c,limb[1]};memcpy(matrix,m,sizeof(m));evidence[0]=best.texture;evidence[1]=best.phase;return 1;
    }catch(const std::exception &e){problem(error,e);return 0;}
}

extern "C" int mn_photo_sun(const uint8_t *grayPixels,const uint8_t *validPixels,const double *vectors,int width,int height,double sun[3]) {
    try {
        cv::Mat raw(height,width,CV_8U,const_cast<uint8_t *>(grayPixels)),gray,valid(height,width,CV_8U,const_cast<uint8_t *>(validPixels));raw.convertTo(gray,CV_32F);cv::GaussianBlur(gray,gray,cv::Size(),1.2);std::vector<double> values;
        for(int i=0;i<width*height;++i)if(validPixels[i])values.push_back(gray.ptr<float>()[i]);if(values.size()<128)return 0;double floor=percentile(values,.02),bright=percentile(values,.9);if(bright-floor<18||floor>bright*.25)return 0;
        cv::Mat dark=(gray<floor+(bright-floor)*.085)&valid,labels,stats,centroids;int components=cv::connectedComponentsWithStats(dark,labels,stats,centroids,8);std::set<int> touching;
        for(int y=0;y<height;++y)for(int x=0;x<width;++x)if(validPixels[y*width+x]&&(x==0||y==0||x==width-1||y==height-1||!validPixels[y*width+std::max(0,x-1)]||!validPixels[y*width+std::min(width-1,x+1)]||!validPixels[std::max(0,y-1)*width+x]||!validPixels[std::min(height-1,y+1)*width+x]))touching.insert(labels.at<int>(y,x));
        touching.erase(0);for(auto i=touching.begin();i!=touching.end();)if(*i>=components||stats.at<int>(*i,cv::CC_STAT_AREA)<=values.size()*.025)i=touching.erase(i);else ++i;
        std::vector<int> selected;std::vector<double> target;int dayCount=0,nightCount=0;
        for(int i=0;i<width*height;++i)if(validPixels[i]){bool night=touching.count(labels.at<int>(i/width,i%width)),day=gray.ptr<float>()[i]>floor+(bright-floor)*.3;if(day||night){selected.push_back(i);target.push_back(day?1:0);if(day)++dayCount;else ++nightCount;}}
        if(nightCount<values.size()*.04||dayCount<values.size()*.08)return 0;int step=std::max(1,(int)selected.size()/20000),count=((int)selected.size()+step-1)/step;
        int sampledDays=0,sampledNights=0;for(int i=0;i<(int)selected.size();i+=step){if(target[i])++sampledDays;else ++sampledNights;}
        cv::Mat samples(count,3,CV_64F),weights(count,1,CV_64F),targets(count,1,CV_64F);for(int j=0,i=0;i<(int)selected.size();i+=step,++j){for(int k=0;k<3;++k)samples.at<double>(j,k)=vectors[selected[i]*3+k];targets.at<double>(j)=target[i];weights.at<double>(j)=target[i]?.8/std::max(1,sampledDays):.2/std::max(1,sampledNights);}
        cv::Mat weighted=samples.clone();for(int i=0;i<count;++i)weighted.row(i)*=weights.at<double>(i);cv::Mat eigenvalues,axes;cv::eigen(samples.t()*weighted,eigenvalues,axes);cv::Mat diagonal=cv::Mat::zeros(3,3,CV_64F);for(int i=0;i<3;++i)diagonal.at<double>(i,i)=1/sqrt(std::max(1e-8,eigenvalues.at<double>(i)));cv::Mat transform=axes.t()*diagonal*axes,features=samples*transform,beta=cv::Mat::zeros(3,1,CV_64F);
        for(int iteration=0;iteration<20;++iteration){cv::Mat z=features*beta,gradient=cv::Mat::zeros(3,1,CV_64F),hessian=cv::Mat::eye(3,3,CV_64F)*.0005;
            for(int row=0;row<count;++row){double p=1/(1+exp(-std::clamp(z.at<double>(row),-40.,40.))),w=weights.at<double>(row);for(int a=0;a<3;++a){gradient.at<double>(a)+=features.at<double>(row,a)*w*(p-targets.at<double>(row));for(int b=0;b<3;++b)hessian.at<double>(a,b)+=features.at<double>(row,a)*features.at<double>(row,b)*w*p*(1-p);}}
            gradient+=.0005*beta;cv::Mat change;if(!cv::solve(hessian,gradient,change,cv::DECOMP_CHOLESKY))return 0;beta-=change;if(cv::norm(change)<1e-5)break;
        }
        cv::Mat normal=transform*beta;double norm=cv::norm(normal);if(norm<1e-8)return 0;normal/=norm;int dayOK=0,nightOK=0;
        for(size_t j=0;j<selected.size();++j){double incidence=0;for(int k=0;k<3;++k)incidence+=vectors[selected[j]*3+k]*normal.at<double>(k);if(target[j]&&incidence>0)++dayOK;else if(!target[j]&&incidence<0)++nightOK;}
        if(double(dayOK)/dayCount<.9||double(nightOK)/nightCount<.85)return 0;for(int k=0;k<3;++k)sun[k]=normal.at<double>(k);return 1;
    }catch(...){return 0;}
}

namespace {
struct TriangleSet {cv::Mat descriptors;std::vector<std::array<int,3>> triangles;};
TriangleSet triangleIndex(const std::vector<cv::Point2d> &points,const std::vector<double> &radii,const std::vector<int> &indices,int neighbours,bool centered) {
    TriangleSet result;if(indices.size()<3)return result;cv::Mat data((int)indices.size(),2,CV_32F);
    for(size_t i=0;i<indices.size();++i){data.at<float>(i,0)=(float)points[indices[i]].x;data.at<float>(i,1)=(float)points[indices[i]].y;}
    cv::flann::Index tree(data,cv::flann::KDTreeIndexParams(2));int k=std::min(neighbours+1,(int)indices.size());cv::Mat near,distances;tree.knnSearch(data,near,distances,k,cv::flann::SearchParams(32));
    std::set<std::array<int,3>> unique;
    for(size_t i=0;i<indices.size();++i){std::vector<int> choices;for(int j=0;j<k;++j)if(near.at<int>((int)i,j)!=(int)i)choices.push_back(indices[near.at<int>((int)i,j)]);
        for(size_t a=0;a<choices.size();++a)for(size_t b=a+1;b<choices.size();++b){std::array<int,3> triangle{indices[i],choices[a],choices[b]};std::sort(triangle.begin(),triangle.end());unique.insert(triangle);}}
    std::vector<float> rows;
    for(auto triple:unique){auto a=points[triple[0]],b=points[triple[1]],c=points[triple[2]];std::array<double,3> side{cv::norm(b-c),cv::norm(a-c),cv::norm(a-b)};std::array<int,3> order{0,1,2};std::sort(order.begin(),order.end(),[&](int x,int y){return side[x]<side[y];});
        double shortest=side[order[0]],middle=side[order[1]],longest=side[order[2]],area=std::abs((b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x));
        if(shortest<=0||area<=.12*longest*longest||shortest<=.18*longest||std::min(middle-shortest,longest-middle)<=.025*longest)continue;
        std::array<int,3> canonical{triple[order[0]],triple[order[1]],triple[order[2]]};double size[3];for(int i=0;i<3;++i)size[i]=.14*log(std::max(1e-6,radii[canonical[i]]/longest));
        double mean=centered?(size[0]+size[1]+size[2])/3:0;rows.push_back((float)(shortest/longest));rows.push_back((float)(middle/longest));for(double value:size)rows.push_back((float)(value-mean));result.triangles.push_back(canonical);
    }
    if(!rows.empty())result.descriptors=cv::Mat((int)result.triangles.size(),5,CV_32F,rows.data()).clone();return result;
}
cv::Mat triangleFit(const std::vector<cv::Point2d> &source,const std::vector<cv::Point2d> &target,double &rms) {
    std::vector<double> s,t;for(auto p:source){s.push_back(p.x);s.push_back(p.y);}for(auto p:target){t.push_back(p.x);t.push_back(p.y);}double m[6];int suspect;char error[1024]={};
    if(!mn_fit_similarity(s.data(),t.data(),(int)source.size(),-1,m,&rms,nullptr,nullptr,&suspect,error))return {};return affine(m);
}
struct VerifiedPair {int source,target;double error;};
struct TriangleSolution {double score;cv::Mat matrix;std::vector<VerifiedPair> pairs;};
TriangleSolution triangleSearch(const std::vector<cv::Point2d> &points,const std::vector<double> &radii,const int *named,const std::vector<cv::Point2d> &photo,const std::vector<double> &observed,
                                  int width,int height,const std::vector<cv::Point2d> &foreground,bool expanded,MNTask *task) {
    int minimum=expanded?7:std::max(7,(int)ceil(photo.size()*.35));TriangleSet reference,observation;std::vector<int> photoIndices(photo.size());std::iota(photoIndices.begin(),photoIndices.end(),0);
    if(expanded){for(double limit:{5,10,20,40,80}){std::vector<int> indices;for(size_t i=0;i<points.size();++i)if(radii[i]*2*1737.4>=limit)indices.push_back((int)i);auto cohort=triangleIndex(points,radii,indices,24,true);reference.triangles.insert(reference.triangles.end(),cohort.triangles.begin(),cohort.triangles.end());if(!cohort.descriptors.empty())reference.descriptors.push_back(cohort.descriptors);}
        std::sort(photoIndices.begin(),photoIndices.end(),[&](int a,int b){return observed[a]>observed[b];});if(photoIndices.size()>20)photoIndices.resize(20);observation=triangleIndex(photo,observed,photoIndices,19,true);
    }else{std::vector<int> indices;for(size_t i=0;i<points.size();++i)if(named[i]&&radii[i]*2*1737.4>=5)indices.push_back((int)i);reference=triangleIndex(points,radii,indices,16,false);observation=triangleIndex(photo,observed,photoIndices,12,false);}
    if(reference.descriptors.empty()||observation.descriptors.empty())throw std::runtime_error("没有足够分散的环形山图案。");
    cv::flann::Index index(reference.descriptors,cv::flann::KDTreeIndexParams(4));cv::Mat neighbours,distances;int k=std::min(expanded?128:8,reference.descriptors.rows);index.knnSearch(observation.descriptors,neighbours,distances,k,cv::flann::SearchParams(expanded?512:64));
    struct Proposal{double distance;int reference,photo;};std::vector<Proposal> proposals;for(int i=0;i<neighbours.rows;++i)for(int j=0;j<k;++j)if(distances.at<float>(i,j)<.095*.095)proposals.push_back({distances.at<float>(i,j),neighbours.at<int>(i,j),i});
    std::sort(proposals.begin(),proposals.end(),[](auto a,auto b){return a.distance<b.distance;});if(proposals.size()>size_t(expanded?50000:2400))proposals.resize(expanded?50000:2400);
    cv::Mat photoData((int)photo.size(),2,CV_32F);for(size_t i=0;i<photo.size();++i){photoData.at<float>(i,0)=(float)photo[i].x;photoData.at<float>(i,1)=(float)photo[i].y;}cv::flann::Index imageIndex(photoData,cv::flann::KDTreeIndexParams(2));std::set<int> core(photoIndices.begin(),photoIndices.end());
    double minRadius=*std::min_element(observed.begin(),observed.end()),maxRadius=*std::max_element(observed.begin(),observed.end());
    auto verify=[&](const cv::Mat &matrix){TriangleSolution solution{0,matrix,{}};cv::Mat inverse;cv::invertAffineTransform(matrix,inverse);int onDisk=0;for(auto p:foreground)if(cv::norm(transform(inverse,p))<1.01)++onDisk;if(!foreground.empty()&&onDisk<foreground.size()*.9)return solution;
        double scale=sqrt(std::abs(matrix.at<double>(0,0)*matrix.at<double>(1,1)-matrix.at<double>(0,1)*matrix.at<double>(1,0)));std::vector<int> indices;std::vector<cv::Point2f> predicted;
        for(size_t i=0;i<points.size();++i){auto p=transform(matrix,points[i]);double radius=radii[i]*scale;if(p.x>=0&&p.y>=0&&p.x<width&&p.y<height&&radius>=minRadius*.55&&radius<=maxRadius*1.6){indices.push_back((int)i);predicted.emplace_back(p);}}
        if((int)indices.size()<minimum)return solution;cv::Mat queries((int)predicted.size(),2,CV_32F,predicted.data()),nearest,distance;imageIndex.knnSearch(queries,nearest,distance,std::min(4,(int)photo.size()),cv::flann::SearchParams(48));
        struct Choice{double quality,error;int source,target;};std::vector<Choice> choices;
        for(int i=0;i<nearest.rows;++i)for(int j=0;j<nearest.cols;++j){int source=indices[i],target=nearest.at<int>(i,j);double ratio=observed[target]/(radii[source]*scale),threshold=std::max(8.,std::min(25.,observed[target]*.25)),error=sqrt(distance.at<float>(i,j));if(ratio>.5&&ratio<1.9&&error<threshold)choices.push_back({error/threshold+.25*std::abs(log(ratio)),error,source,target});}
        std::sort(choices.begin(),choices.end(),[](auto a,auto b){return a.quality<b.quality;});std::set<int> usedSource,usedTarget;int namedCount=0,coreCount=0;std::vector<cv::Point2f> occupied;
        for(auto c:choices)if(!usedSource.count(c.source)&&!usedTarget.count(c.target)){solution.pairs.push_back({c.source,c.target,c.error});usedSource.insert(c.source);usedTarget.insert(c.target);occupied.emplace_back(photo[c.target]);namedCount+=named[c.source]!=0;coreCount+=core.count(c.target);}
        if((int)solution.pairs.size()<minimum||(!expanded&&namedCount<4)||(expanded&&coreCount<minimum)||hullArea(occupied)/(double(width)*height)<.06)return solution;
        for(auto pair:solution.pairs)solution.score+=sqrt(observed[pair.target])*(expanded?1:(named[pair.source]?1.25:.8))*(1-.5*std::min(1.,pair.error/std::max(8.,std::min(25.,observed[pair.target]*.25))));return solution;
    };
    std::set<std::array<long,7>> tried;std::vector<TriangleSolution> solutions;
    for(size_t i=0;i<proposals.size();++i){if(i%32==0)check(task);auto proposal=proposals[i];auto s=reference.triangles[proposal.reference],t=observation.triangles[proposal.photo];double rms;auto m=triangleFit({points[s[0]],points[s[1]],points[s[2]]},{photo[t[0]],photo[t[1]],photo[t[2]]},rms);
        if(m.empty()||rms>std::max(4.,(observed[t[0]]+observed[t[1]]+observed[t[2]])/3*.15))continue;double scale=sqrt(std::abs(cv::determinant(m(cv::Rect(0,0,2,2)))));if(scale<=100||scale>=1e6)continue;
        std::array<long,7> key{lround(m.at<double>(0,0)/std::max(1.,scale*.025)),lround(m.at<double>(0,1)/std::max(1.,scale*.025)),lround(m.at<double>(1,0)/std::max(1.,scale*.025)),lround(m.at<double>(1,1)/std::max(1.,scale*.025)),lround(m.at<double>(0,2)/25),lround(m.at<double>(1,2)/25),lround(log(scale)*40)};
        if(!tried.insert(key).second)continue;auto candidate=verify(m);if(candidate.score>0)solutions.push_back(candidate);
    }
    if(solutions.empty())throw std::runtime_error("未找到通过多坑验证的月面区域。");std::sort(solutions.begin(),solutions.end(),[](const auto &a,const auto &b){return a.score>b.score;});auto best=solutions.front();
    for(int iteration=0;iteration<2;++iteration){std::vector<cv::Point2d> s,t;for(auto pair:best.pairs){s.push_back(points[pair.source]);t.push_back(photo[pair.target]);}double rms;auto m=triangleFit(s,t,rms);if(m.empty())break;auto refined=verify(m);if(refined.score<.9*best.score)break;best=refined;}
    cv::Mat inverse;cv::invertAffineTransform(best.matrix,inverse);std::vector<cv::Point2d> probes{{width/2.,height/2.},{width*.75,height/2.},{width/2.,height*.75}};
    for(const auto &other:solutions)if(other.score>best.score*.8){double difference=0;for(auto p:probes)difference+=cv::norm(transform(other.matrix,transform(inverse,p))-p);if(difference/3>std::max(width,height)*.08)throw std::runtime_error("出现多个接近的月面匹配，无法可靠区分。");}
    return best;
}
}
extern "C" int mn_triangles(const double *coordinates,const double *radii,const int *named,int featureCount,const MNCandidate *candidates,int candidateCount,int width,int height,
                              const uint8_t *photoPixels,int channels,const uint8_t *mask,MNTask *task,MNMatch *result,double *score,char error[1024]) {
    memset(result,0,sizeof(*result));
    try {
        if(candidateCount<7)throw std::runtime_error("可用坑缘不足七处，无法独立验证自动识别。");cv::setRNGSeed(0);std::vector<cv::Point2d> points,photo,foreground;std::vector<double> sizes,observed;
        for(int i=0;i<featureCount;++i){points.emplace_back(coordinates[2*i],coordinates[2*i+1]);sizes.push_back(radii[i]);}for(int i=0;i<candidateCount;++i){photo.emplace_back(candidates[i].x,candidates[i].y);observed.push_back(candidates[i].major);}
        auto image=gray(photoPixels,width,height,channels);int limit=(int)round(height*.93);cv::Mat small;cv::resize(image(cv::Rect(0,0,width,limit)),small,{40,36},0,0,cv::INTER_AREA);
        for(int y=0;y<36;++y)for(int x=0;x<40;++x)if(small.at<uint8_t>(y,x)>30){cv::Point2d p((x+.5)*width/40,(y+.5)*limit/36);if(!mask||mask[(int)p.y*width+(int)p.x])foreground.push_back(p);}
        TriangleSolution best;try{best=triangleSearch(points,sizes,named,photo,observed,width,height,foreground,false,task);}catch(const std::exception &e){check(task);if(std::string(e.what()).find("多个接近")!=std::string::npos)throw;best=triangleSearch(points,sizes,named,photo,observed,width,height,foreground,true,task);}
        std::vector<cv::Point2d> source,target;std::vector<cv::Point2f> domain;double square=0;
        result->feature_indices=(int *)malloc(best.pairs.size()*sizeof(int));result->candidate_indices=(int *)malloc(best.pairs.size()*sizeof(int));if(!result->feature_indices||!result->candidate_indices)throw std::bad_alloc();
        for(size_t i=0;i<best.pairs.size();++i){auto pair=best.pairs[i];source.push_back(points[pair.source]);target.push_back(photo[pair.target]);domain.emplace_back(photo[pair.target]);result->feature_indices[i]=pair.source;result->candidate_indices[i]=pair.target;square+=pair.error*pair.error;}
        result->source=copyPoints(source);result->target=copyPoints(target);result->count=(int)best.pairs.size();result->matches=candidateCount;result->rms=sqrt(square/best.pairs.size());result->coverage=hullArea(domain)/(double(width)*height);memcpy(result->matrix,best.matrix.ptr<double>(),6*sizeof(double));*score=best.score;return 1;
    }catch(const std::exception &e){mn_match_destroy(result);problem(error,e);return 0;}
}

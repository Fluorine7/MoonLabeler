// SPDX-License-Identifier: GPL-3.0-or-later
// Port of moonlabeler/eyepiece_refinement.py. Keep its acceptance gates together.
#include "EyepieceModel.hpp"
#include <opencv2/flann.hpp>
#include <array>
#include <map>
#include <numeric>

using namespace moonoptics;
namespace {
double percentile(std::vector<double> values,double fraction) {
    if(values.empty())return INFINITY;std::sort(values.begin(),values.end());double index=fraction*(values.size()-1);size_t i=size_t(index);
    return values[i]*(1-(index-i))+values[std::min(i+1,values.size()-1)]*(index-i);
}
bool allowed(const uint8_t *mask,int width,int height,cv::Point2d point) {
    if(!std::isfinite(point.x)||!std::isfinite(point.y)||point.x<0||point.y<0||point.x>=width||point.y>=height)return false;
    return !mask||mask[int(point.y)*width+int(point.x)];
}
cv::Mat pointsMat(const std::vector<cv::Point2d> &points) {
    cv::Mat output(int(points.size()),2,CV_32F);for(size_t i=0;i<points.size();++i){output.at<float>(int(i),0)=float(points[i].x);output.at<float>(int(i),1)=float(points[i].y);}return output;
}
cv::Mat enhance(const cv::Mat &image) {cv::Mat output;cv::createCLAHE(2.,{8,8})->apply(image,output);return output;}
std::vector<cv::Point2d> nearest(const std::vector<cv::Point2d> &query,const cv::Mat &measured) {
    cv::FlannBasedMatcher matcher(cv::makePtr<cv::flann::KDTreeIndexParams>(1),cv::makePtr<cv::flann::SearchParams>(64));
    std::vector<std::vector<cv::DMatch>> matches;matcher.knnMatch(pointsMat(query),measured,matches,1);std::vector<cv::Point2d> output;
    for(auto &row:matches){int i=row.at(0).trainIdx;output.emplace_back(measured.at<float>(i,0),measured.at<float>(i,1));}return output;
}
struct Boundary {cv::Mat gray,distances;double factor;std::vector<cv::Point> contour;};
Boundary boundary(const uint8_t *photo,int width,int height,const uint8_t *mask,int maximum) {
    Boundary result;result.factor=std::min(1.,double(maximum)/std::max(width,height));auto original=gray(photo,width,height,4);
    cv::resize(original,result.gray,cv::Size(),result.factor,result.factor,cv::INTER_AREA);std::vector<double> intensities;
    for(int y=0;y<result.gray.rows;++y)for(int x=0;x<result.gray.cols;++x)if(allowed(mask,width,height,{x/result.factor,y/result.factor}))intensities.push_back(result.gray.at<uint8_t>(y,x));
    if(intensities.empty())throw std::runtime_error("目镜校正缺少可验证的受光月缘。");
    cv::Mat bright;cv::compare(result.gray,std::max(30.,percentile(intensities,.99)*.25),bright,cv::CMP_GT);
    std::vector<std::vector<cv::Point>> contours;cv::findContours(bright,contours,cv::RETR_EXTERNAL,cv::CHAIN_APPROX_NONE);
    double largest=-1;for(auto &candidate:contours){bool usable=!mask;for(auto p:candidate)if(allowed(mask,width,height,{p.x/result.factor,p.y/result.factor})){usable=true;break;}
        double area=cv::contourArea(candidate);if(usable&&area>largest){largest=area;result.contour=candidate;}}
    if(result.contour.empty())throw std::runtime_error("目镜校正缺少可验证的受光月缘。");
    cv::Mat pixels(result.gray.size(),CV_8U,cv::Scalar(1));cv::drawContours(pixels,std::vector<std::vector<cv::Point>>{result.contour},0,cv::Scalar(0),1);
    if(mask)for(int y=0;y<pixels.rows;++y)for(int x=0;x<pixels.cols;++x)if(!allowed(mask,width,height,{x/result.factor,y/result.factor}))pixels.at<uint8_t>(y,x)=1;
    cv::distanceTransform(pixels,result.distances,cv::DIST_L2,5);result.distances/=result.factor;return result;
}
struct LimbData {std::vector<cv::Point2d> train,hold;cv::Mat measuredTrain,measuredHold;double factor;};
LimbData limbData(const uint8_t *photo,int width,int height,const uint8_t *mask,const ViewGeometry &effective,
                  const double camera[6],const double lens[4],const cv::Mat &initial,cv::Point2d center,double scale,int sign) {
    auto observed=boundary(photo,width,height,mask,1800);LimbData data;data.factor=observed.factor;
    cv::Mat inverse;cv::invertAffineTransform(affine(camera),inverse);std::vector<cv::Point2d> measured[2];
    for(auto p:observed.contour){cv::Point2d pixel(float(p.x/observed.factor),float(p.y/observed.factor));if(!allowed(mask,width,height,pixel))continue;
        auto delta=(pixel-cv::Point2d(lens[0],lens[1]))/lens[2];double radius=cv::norm(delta),original=std::min(radius,cbrt(radius/lens[3]));
        for(int i=0;i<12;++i)original-=(original+lens[3]*original*original*original-radius)/(1+3*lens[3]*original*original);
        auto model=transform(inverse,cv::Point2d(lens[0],lens[1])+delta*(original/std::max(radius,1e-30))*lens[2]);double modelRadius=cv::norm(model);
        if(modelRadius<=.94||modelRadius>=1.06)continue;double angle=atan2(model.y,model.x);if(angle<0)angle+=2*M_PI;
        int index=int(floor(angle*360/M_PI));measured[(index/4)%2].push_back(pixel);
    }
    if(measured[0].size()<100||measured[1].size()<100)throw std::runtime_error("目镜校正缺少可验证的受光月缘。");
    data.measuredTrain=pointsMat(measured[0]);data.measuredHold=pointsMat(measured[1]);
    for(int i=0;i<720;++i){double t=i*M_PI/360;cv::Point2d circle(cos(t),sin(t));if(effective.unproject(circle*.999).dot(effective.sun)<=.15)continue;
        auto pixel=opticalRadial(initial,circle,sign)*scale+center;if(pixel.x<=3||pixel.y<=3||pixel.x>=width-4||pixel.y>=height-4||!allowed(mask,width,height,pixel))continue;
        ((i/4)%2?data.hold:data.train).push_back(circle);
    }
    if(data.train.size()<100||data.hold.size()<100)throw std::runtime_error("目镜校正的可验证月缘不足 120°。");return data;
}
cv::Mat fit(const cv::Mat &initial,const std::vector<cv::Vec3d> &surface,const std::vector<cv::Point2d> &target,
            const ViewGeometry &g,int sign,double scale,cv::Point2d center,const LimbData &limb,MNTask *task) {
    auto params=initial.clone();double damping=.001;
    auto predict=[&](const cv::Mat &p){auto result=opticalPredict(p,g,surface,sign);for(auto circle:limb.train)result.push_back(opticalRadial(p,circle,sign));return result;};
    auto targets=[&](const std::vector<cv::Point2d> &p){std::vector<cv::Point2d> query;for(size_t i=surface.size();i<p.size();++i)query.push_back(p[i]*scale+center);
        auto measured=nearest(query,limb.measuredTrain);auto result=target;for(auto pixel:measured)result.push_back((pixel-center)/scale);return result;};
    auto cost=[](double e){return e<3?e*e:6*e-9;};
    for(int iteration=0;iteration<80;++iteration){check(task);auto predicted=predict(params),observed=targets(predicted);int rows=int(predicted.size())*2;
        cv::Mat residual(rows,1,CV_64F),jacobian(rows,10,CV_64F),weights(rows,1,CV_64F);double before=0;
        for(size_t i=0;i<predicted.size();++i){auto delta=predicted[i]-observed[i];double error=cv::norm(delta)*scale,importance=i<surface.size()?1.:.25;
            before+=importance*cost(error);residual.at<double>(2*i)=delta.x;residual.at<double>(2*i+1)=delta.y;weights.at<double>(2*i)=weights.at<double>(2*i+1)=importance*std::min(1.,3/std::max(error,1e-8));}
        for(int column=0;column<10;++column){auto probe=params.clone();probe.at<double>(column)+=1e-5;auto next=predict(probe);
            for(size_t i=0;i<next.size();++i){auto delta=(next[i]-predicted[i])*1e5;jacobian.at<double>(2*i,column)=delta.x;jacobian.at<double>(2*i+1,column)=delta.y;}}
        cv::Mat weighted=jacobian.clone();for(int i=0;i<rows;++i)weighted.row(i)*=weights.at<double>(i);cv::Mat normal=jacobian.t()*weighted,rhs=jacobian.t()*(weights.mul(residual)),delta;
        for(int i=0;i<10;++i)normal.at<double>(i,i)+=damping*std::max(normal.at<double>(i,i),1e-8);
        if(!cv::solve(normal,rhs,delta,cv::DECOMP_CHOLESKY))throw std::runtime_error("目镜校正的分区验证失败。");
        cv::Mat trial=params-delta;trial.at<double>(4)=std::clamp(trial.at<double>(4),0.,.6);for(int i=5;i<7;++i)trial.at<double>(i)=std::clamp(trial.at<double>(i),-.7,.7);
        for(int i=7;i<9;++i)trial.at<double>(i)=std::clamp(trial.at<double>(i),-1.25,1.25);trial.at<double>(9)=std::clamp(trial.at<double>(9),-.3,.3);
        auto updated=predict(trial),expected=targets(updated);double after=0;for(size_t i=0;i<updated.size();++i)after+=(i<surface.size()?1.:.25)*cost(cv::norm(updated[i]-expected[i])*scale);
        if(after<before){params=trial;damping=std::max(1e-8,damping/3);if(cv::norm(delta)<1e-7)break;}else if((damping*=10)>1e12)break;
    }return params;
}
bool physical(const cv::Mat &p,int sign) {
    if(!cv::checkRange(p)||p.at<double>(4)<=.015||p.at<double>(4)>=.55||hypot(p.at<double>(7),p.at<double>(8))>1.25)return false;
    for(int i=0;i<360;++i){double t=i*M_PI/180,x=cos(t)*sign,y=sin(t),a=p.at<double>(0),b=p.at<double>(1);
        cv::Point2d ideal(a*x-b*y+p.at<double>(2)-p.at<double>(5),b*x+a*y+p.at<double>(3)-p.at<double>(6));double squared=ideal.dot(ideal);
        if(1+3*p.at<double>(4)*squared+5*p.at<double>(9)*squared*squared<=.2)return false;}return true;
}
struct LimbEvidence {std::vector<cv::Point2d> rim;double p95;};
LimbEvidence validateLimb(const uint8_t *photo,int width,int height,const uint8_t *mask,const ViewGeometry &g,
                          const cv::Mat &params,cv::Point2d center,double scale,int sign,double area) {
    auto observed=boundary(photo,width,height,mask,1400);if(cv::contourArea(observed.contour)/pow(observed.factor,2)<area*.1)throw std::runtime_error("目镜校正需要较完整的月面视野。");
    LimbEvidence result;std::vector<double> errors;double margin=g.observer.dot(g.sun)>.98?.02:.15;
    for(int i=0;i<720;++i){double t=2*M_PI*i/720;cv::Point2d circle(cos(t),sin(t));if(g.unproject(circle*.999).dot(g.sun)<=margin)continue;
        auto p=opticalRadial(params,circle,sign)*scale+center;if(p.x<=3||p.y<=3||p.x>=width-4||p.y>=height-4||!allowed(mask,width,height,p))continue;
        int x=int(std::nearbyint(p.x*observed.factor)),y=int(std::nearbyint(p.y*observed.factor));if(x<0||y<0||x>=observed.gray.cols||y>=observed.gray.rows)continue;
        result.rim.push_back(circle);errors.push_back(observed.distances.at<float>(y,x));}
    if(result.rim.size()<240)throw std::runtime_error("目镜校正的可验证月缘不足 120°。");result.p95=percentile(errors,.95);double tolerance=std::max(4/observed.factor,scale*.008);
    if(result.p95>tolerance||percentile(errors,.5)>tolerance*.7)throw std::runtime_error("目镜校正仍与实际受光月缘不一致。");return result;
}
}

extern "C" int mn_eyepiece_edge_matches(const uint8_t *reference,int rw,int rh,const uint8_t *photo,int pw,int ph,
                                        const uint8_t *mask,double maximumDistance,MNTask *task,MNMatch *result,char error[1024]) {
    memset(result,0,sizeof(*result));try {
        check(task);cv::Mat blurred;cv::GaussianBlur(gray(reference,rw,rh,1),blurred,cv::Size(),.65);auto ref=enhance(blurred);
        double ps=std::min(1.,2200./std::max(pw,ph)),sx=double(rw)/pw,sy=double(rh)/ph;auto original=gray(photo,pw,ph,4);cv::Mat small;
        cv::resize(original,small,cv::Size(),ps,ps,cv::INTER_AREA);auto image=enhance(small);cv::Mat rm,pm;
        if(mask){cv::Mat source(ph,pw,CV_8U,const_cast<uint8_t *>(mask));cv::resize(source,rm,ref.size(),0,0,cv::INTER_NEAREST);cv::resize(source,pm,image.size(),0,0,cv::INTER_NEAREST);}
        std::vector<cv::KeyPoint> rk,pk;cv::Mat rd,pd;cv::SIFT::create(10000,3,.01)->detectAndCompute(ref,rm,rk,rd);
        cv::SIFT::create(10000,3,.02)->detectAndCompute(image,pm,pk,pd);
        if(rd.empty()||pd.empty()||rk.size()<40)throw std::runtime_error("高程参考有效纹理不足，未采用结果。");check(task);
        cv::BFMatcher matcher(cv::NORM_L2);std::vector<std::vector<cv::DMatch>> forward,reverse;matcher.knnMatch(rd,pd,forward,2);matcher.knnMatch(pd,rd,reverse,2);
        std::vector<int> back(pk.size(),-1);for(auto &pair:reverse)if(pair.size()==2&&pair[0].distance<.85*pair[1].distance)back[pair[0].queryIdx]=pair[0].trainIdx;
        std::map<std::array<long,4>,std::pair<cv::Point2d,cv::Point2d>> pairs;
        for(auto &pair:forward)if(pair.size()==2&&pair[0].distance<.85*pair[1].distance&&back[pair[0].trainIdx]==pair[0].queryIdx){
            auto rp=rk[pair[0].queryIdx].pt,pp=pk[pair[0].trainIdx].pt;cv::Point2d source(rp.x/sx,rp.y/sy),target(pp.x/ps,pp.y/ps);
            if(cv::norm(source-target)>=maximumDistance||!allowed(mask,pw,ph,source)||!allowed(mask,pw,ph,target))continue;
            std::array<long,4> key{long(std::nearbyint(source.x*4)),long(std::nearbyint(source.y*4)),long(std::nearbyint(target.x*4)),long(std::nearbyint(target.y*4))};pairs.emplace(key,std::make_pair(source,target));}
        std::vector<cv::Point2d> source,target;for(auto &entry:pairs){source.push_back(entry.second.first);target.push_back(entry.second.second);}
        if(source.size()<40)throw std::runtime_error("高程参考有效纹理不足，未采用结果。");result->source=copyPoints(source);result->target=copyPoints(target);result->count=result->matches=int(source.size());return 1;
    }catch(const std::exception &e){mn_match_destroy(result);problem(error,e);return 0;}
}

extern "C" int mn_refine_eyepiece_edges(const double geometry[13],const double projection[6],const double camera[6],const double lens[4],const double offsets[2],
                                         const double *source,const double *target,int originalCount,int count,const uint8_t *photo,int width,int height,const uint8_t *mask,
                                         MNTask *task,double outputGeometry[13],double outputMatrix[6],double outputLens[5],double evidence[14],double folds[36],char error[1024]) {
    try {
        check(task);if(originalCount<64||count-originalCount<80)throw std::runtime_error("目镜校正需要至少 100 个分散的纹理对应点。");
        ViewGeometry g(geometry);cv::Mat inverse;cv::invertAffineTransform(affine(projection),inverse);
        std::map<std::array<long,4>,int> unique;for(int i=0;i<count;++i){std::array<long,4> key;for(int c=0;c<2;++c){key[c]=long(std::nearbyint(source[2*i+c]*8));key[2+c]=long(std::nearbyint(target[2*i+c]*8));}unique.emplace(key,i);}
        std::vector<cv::Vec3d> allSurface;std::vector<cv::Point2d> allPixels;std::vector<bool> allNew;
        for(auto &entry:unique){int i=entry.second;try{allSurface.push_back(g.unproject(transform(inverse,{source[2*i],source[2*i+1]})));allPixels.emplace_back(target[2*i],target[2*i+1]);allNew.push_back(i>=originalCount);}catch(const std::runtime_error &) {}}
        std::vector<cv::Vec3d> surface;std::vector<cv::Point2d> pixels;std::vector<bool> added;size_t samples=std::min<size_t>(800,allSurface.size());
        for(size_t i=0;i<samples;++i){size_t index=samples==allSurface.size()?i:i*(allSurface.size()-1)/(samples-1);surface.push_back(allSurface[index]);pixels.push_back(allPixels[index]);added.push_back(allNew[index]);}
        if(surface.size()<100)throw std::runtime_error("目镜校正需要至少 100 个分散的纹理对应点。");
        double scale=lens[2];cv::Point2d center(width/2.,height/2.);if(std::max(std::abs(lens[0]-center.x),std::abs(lens[1]-center.y))/scale>.5)center={lens[0],lens[1]};
        int sign=camera[0]*camera[4]-camera[1]*camera[3]<0?-1:1;
        cv::Mat initial=(cv::Mat_<double>(10,1)<<camera[0]/sign/scale,camera[3]/sign/scale,(camera[2]-center.x)/scale,(camera[5]-center.y)/scale,lens[3],(lens[0]-center.x)/scale,(lens[1]-center.y)/scale,offsets[0],offsets[1],0.);
        auto limb=limbData(photo,width,height,mask,g.shifted(offsets[0],offsets[1]),camera,lens,initial,center,scale,sign);
        std::vector<cv::Point2d> normalized;for(auto p:pixels)normalized.push_back((p-center)/scale);
        auto params=fit(initial,surface,normalized,g,sign,scale,center,limb,task);if(!physical(params,sign))throw std::runtime_error("目镜校正参数未通过验证。");
        auto predicted=opticalPredict(params,g,surface,sign),before=opticalPredict(initial,g,surface,sign);std::vector<int> inliers;std::vector<cv::Point2f> occupied;std::vector<double> oldError,newError;double square=0;
        for(size_t i=0;i<surface.size();++i){double e=cv::norm(predicted[i]-normalized[i])*scale;if(e<3){inliers.push_back(int(i));occupied.emplace_back(pixels[i]);square+=e*e;}if(added[i]){oldError.push_back(cv::norm(before[i]-normalized[i])*scale);newError.push_back(e);}}
        double area=std::min(double(width)*height,4*scale*scale),coverage=hullArea(occupied)/area;
        if(inliers.size()<100||double(inliers.size())/surface.size()<.8||coverage<.08)throw std::runtime_error("目镜校正的纹理验证不足。");
        auto effective=g.shifted(params.at<double>(7),params.at<double>(8));auto independent=validateLimb(photo,width,height,mask,effective,params,center,scale,sign,area);
        std::vector<cv::Point2d> held;for(auto p:limb.hold)held.push_back(opticalRadial(params,p,sign)*scale+center);auto heldTarget=nearest(held,limb.measuredHold);std::vector<double> heldError;
        for(size_t i=0;i<held.size();++i)heldError.push_back(cv::norm(held[i]-heldTarget[i]));double tolerance=std::max(4/limb.factor,scale*.008),heldP95=percentile(heldError,.95);
        if(heldP95>tolerance||percentile(heldError,.5)>tolerance*.7)throw std::runtime_error("目镜校正仍与实际受光月缘不一致。");
        std::vector<cv::Vec3d> oldSurface;std::vector<cv::Point2d> oldPixels;for(int i=0;i<originalCount;++i)try{oldSurface.push_back(g.unproject(transform(inverse,{source[2*i],source[2*i+1]})));oldPixels.emplace_back(target[2*i],target[2*i+1]);}catch(const std::runtime_error &) {}
        auto oldBefore=opticalPredict(initial,g,oldSurface,sign),oldAfter=opticalPredict(params,g,oldSurface,sign);std::vector<double> reliableBefore,reliableAfter;int reliableWithin=0;
        for(size_t i=0;i<oldSurface.size();++i){double b=cv::norm(oldBefore[i]*scale+center-oldPixels[i]);if(b>=3)continue;double a=cv::norm(oldAfter[i]*scale+center-oldPixels[i]);reliableBefore.push_back(b);reliableAfter.push_back(a);if(a<4)++reliableWithin;}
        if(reliableBefore.empty()||double(reliableWithin)/reliableBefore.size()<.95||percentile(reliableAfter,.5)>percentile(reliableBefore,.5)+1)throw std::runtime_error("目镜校正的分区预测不稳定。");
        double medianBefore=percentile(oldError,.5),medianAfter=percentile(newError,.5);if(newError.size()<80||medianBefore-medianAfter<.75||medianAfter>.75*medianBefore)return 2;
        cv::Point2d lower(INFINITY,INFINITY),upper(-INFINITY,-INFINITY);for(int i:inliers){lower.x=std::min(lower.x,pixels[i].x);lower.y=std::min(lower.y,pixels[i].y);upper.x=std::max(upper.x,pixels[i].x);upper.y=std::max(upper.y,pixels[i].y);}
        std::vector<int> cells;for(auto p:pixels)cells.push_back(std::clamp(int((p.x-lower.x)/std::max(upper.x-lower.x,1.)*3),0,2)+3*std::clamp(int((p.y-lower.y)/std::max(upper.y-lower.y,1.)*3),0,2));
        int foldCount=0;for(int cell=0;cell<9;++cell){check(task);std::vector<cv::Vec3d> train,hold;std::vector<cv::Point2d> tt,ht;for(size_t i=0;i<surface.size();++i)if(cells[i]==cell){hold.push_back(surface[i]);ht.push_back(normalized[i]);}else{train.push_back(surface[i]);tt.push_back(normalized[i]);}
            if(hold.size()<10)continue;auto other=fit(initial,train,tt,g,sign,scale,center,limb,task);auto checks=opticalPredict(other,g,hold,sign);std::vector<double> errors,delta;int within=0;
            for(size_t i=0;i<hold.size();++i){double e=cv::norm(checks[i]-ht[i])*scale;errors.push_back(e);if(e<4)++within;}
            for(auto p:independent.rim)delta.push_back(cv::norm(opticalRadial(other,p,sign)-opticalRadial(params,p,sign))*scale);
            double fraction=double(within)/hold.size();if(!physical(other,sign)||fraction<.8||percentile(delta,.95)>std::max(3.,scale*.006))throw std::runtime_error("目镜校正的分区预测不稳定。");
            folds[4*foldCount]=cell;folds[4*foldCount+1]=hold.size();folds[4*foldCount+2]=percentile(errors,.5);folds[4*foldCount+3]=fraction;++foldCount;}
        if(foldCount<4)throw std::runtime_error("目镜校正缺少独立的验证区域。");effective.store(outputGeometry);double a=params.at<double>(0),b=params.at<double>(1);
        double matrix[]={a*sign*scale,-b*scale,params.at<double>(2)*scale+center.x,b*sign*scale,a*scale,params.at<double>(3)*scale+center.y};memcpy(outputMatrix,matrix,sizeof(matrix));
        outputLens[0]=center.x+scale*params.at<double>(5);outputLens[1]=center.y+scale*params.at<double>(6);outputLens[2]=scale;outputLens[3]=params.at<double>(4);outputLens[4]=params.at<double>(9);
        double values[]={sqrt(square/inliers.size()),double(inliers.size()),coverage,independent.p95,independent.rim.size()/2.,params.at<double>(7),params.at<double>(8),double(count-originalCount),medianBefore,medianAfter,double(limb.train.size()),double(limb.hold.size()),heldP95,double(foldCount)};memcpy(evidence,values,sizeof(values));return 1;
    }catch(const std::exception &e){problem(error,e);return 0;}
}

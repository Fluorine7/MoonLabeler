// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "Internal.hpp"
#include <algorithm>

namespace moonoptics {
struct ViewGeometry {
    cv::Vec3d observer,right,north,sun;double distance;
    explicit ViewGeometry(const double *g):observer(g[0],g[1],g[2]),right(g[3],g[4],g[5]),north(g[6],g[7],g[8]),sun(g[9],g[10],g[11]),distance(g[12]){}
    ViewGeometry shifted(double x,double y)const {auto g=*this;g.observer=cv::normalize(observer+tan(x*M_PI/180)*right+tan(y*M_PI/180)*north);g.north=cv::normalize(north-north.dot(g.observer)*g.observer);g.right=cv::normalize(g.north.cross(g.observer));return g;}
    cv::Point2d project(cv::Vec3d surface)const {double perspective=1-1737.4/distance*surface.dot(observer);return {surface.dot(right)/perspective,-surface.dot(north)/perspective};}
    cv::Vec3d unproject(cv::Point2d p)const {double d=distance/1737.4;auto ray=-observer+(p.x*right-p.y*north)/d;double a=ray.dot(ray),disc=d*d-a*(d*d-1);if(disc<0)throw std::runtime_error("参考对应点位于月盘外。");double length=(d*d-1)/(d+sqrt(disc));return d*observer+length*ray;}
    void store(double *g)const {for(int i=0;i<3;++i){g[i]=observer[i];g[3+i]=right[i];g[6+i]=north[i];g[9+i]=sun[i];}g[12]=distance;}
};
inline cv::Point2d opticalRadial(const cv::Mat &p,cv::Point2d model,int sign) {
    double a=p.at<double>(0),b=p.at<double>(1);cv::Point2d point(a*model.x*sign-b*model.y+p.at<double>(2),b*model.x*sign+a*model.y+p.at<double>(3));
    cv::Point2d delta=point-cv::Point2d(p.at<double>(5),p.at<double>(6));double squared=delta.dot(delta);
    double radial=p.at<double>(4)*squared;if(p.total()>9)radial+=p.at<double>(9)*squared*squared;return point+radial*delta;
}
inline std::vector<cv::Point2d> opticalPredict(const cv::Mat &p,const ViewGeometry &geometry,const std::vector<cv::Vec3d> &surface,int sign) {
    auto g=geometry.shifted(p.at<double>(7),p.at<double>(8));std::vector<cv::Point2d> result;result.reserve(surface.size());
    for(auto point:surface)result.push_back(opticalRadial(p,g.project(point),sign));return result;
}
}

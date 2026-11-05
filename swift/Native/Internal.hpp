// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "MoonNative.h"
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/features2d.hpp>
#include <opencv2/calib3d.hpp>
#include <atomic>
#include <stdexcept>
#include <cstring>
#include <vector>
#include <cmath>
struct MNTask { std::atomic_bool cancelled{false}; };
inline void check(MNTask *task) { if (task && task->cancelled.load()) throw std::runtime_error("操作已取消。"); }
inline void problem(char *error, const std::exception &e) { if (error) { strncpy(error, e.what(), 1023); error[1023] = 0; } }
inline cv::Mat gray(const uint8_t *pixels, int w, int h, int channels) {
    if (!pixels || w <= 0 || h <= 0 || (channels != 1 && channels != 3 && channels != 4)) throw std::runtime_error("图像参数无效。");
    cv::Mat input(h, w, CV_MAKETYPE(CV_8U, channels), const_cast<uint8_t *>(pixels)), output;
    if (channels == 1) return input;
    cv::cvtColor(input, output, channels == 3 ? cv::COLOR_RGB2GRAY : cv::COLOR_RGBA2GRAY); return output;
}
inline cv::Point2d transform(const cv::Mat &m, cv::Point2d p) {
    return {m.at<double>(0,0)*p.x+m.at<double>(0,1)*p.y+m.at<double>(0,2),
            m.at<double>(1,0)*p.x+m.at<double>(1,1)*p.y+m.at<double>(1,2)};
}
inline cv::Mat affine(const double *values) { return cv::Mat(2,3,CV_64F,const_cast<double *>(values)).clone(); }
inline double hullArea(const std::vector<cv::Point2f> &points) {
    if (points.size()<3) return 0;
    std::vector<cv::Point2f> hull; cv::convexHull(points,hull); return cv::contourArea(hull);
}
inline double *copyPoints(const std::vector<cv::Point2d> &points) {
    auto *result = static_cast<double *>(malloc(points.size()*2*sizeof(double)));
    if (!result && !points.empty()) throw std::bad_alloc();
    for (size_t i=0;i<points.size();++i) { result[2*i]=points[i].x; result[2*i+1]=points[i].y; }
    return result;
}

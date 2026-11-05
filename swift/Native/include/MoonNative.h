// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct MNTask MNTask;
MNTask *mn_task_create(void);
void mn_task_cancel(MNTask *task);
int mn_task_cancelled(MNTask *task);
void mn_task_destroy(MNTask *task);
void mn_free(void *allocation);
char *mn_binary_contours(const uint8_t *mask, int width, int height, char error[1024]);
uint8_t *mn_resize_rgba(const uint8_t *photo, int width, int height, int output_width, int output_height, char error[1024]);
uint8_t *mn_read_jpeg(const char *path, int *width, int *height, char error[1024]);
// Geometry: observer/right/north/sun (four xyz vectors), distance in km.
int mn_ephemeris(const char *kernel_directory, const char *utc, double latitude, double longitude,
                 int topocentric, double delta_t, double geometry[13], char error[1024]);
uint8_t *mn_albedo_atlas(const uint8_t *texture, int width, int height, const double geometry[13],
                         int size, MNTask *task, double *valid_fraction, char error[1024]);
int mn_fit_similarity(const double *source, const double *target, int count, int mirror,
                      double matrix[6], double *rms, double *residuals, double *checks,
                      int *suspect, char error[1024]);
typedef struct {
    double matrix[6];
    double rms, coverage;
    int count, matches, mirrored;
    double *source, *target, *source_matches, *target_matches;
    int *feature_indices, *candidate_indices;
} MNMatch;
int mn_match(const uint8_t *reference, int rw, int rh, int rc,
              const uint8_t *photo, int pw, int ph, int pc, const uint8_t *mask,
              double ratio, double contrast, double fraction, MNTask *task,
              MNMatch *result, char error[1024]);
int mn_local_matches(const uint8_t *reference, const uint8_t *photo, int width, int height, const uint8_t *mask,
                      MNTask *task, MNMatch *result, char error[1024]);
int mn_realign_match(const uint8_t *reference, int rw, int rh, int rc,
                     const uint8_t *photo, int pw, int ph, int pc, const uint8_t *mask,
                     const double coarse[6], MNTask *task, MNMatch *result, char error[1024]);
void mn_match_destroy(MNMatch *match);
typedef struct {
    double x, y, major, minor, angle, score, contrast, support;
    int method;
} MNCandidate;
MNCandidate *mn_detect(const uint8_t *photo, int width, int height, int channels, const uint8_t *mask,
                       double minimum_radius, double maximum_radius, int maximum_count,
                       double sensitivity, MNTask *task, int *count, char error[1024]);
MNCandidate *mn_detect_rims(const uint8_t *photo, int width, int height, int channels, const uint8_t *mask,
                            MNTask *task, int *count, char error[1024]);
int mn_limb(const uint8_t *photo, int width, int height, int channels, const uint8_t *mask,
            MNTask *task, double result[5], char error[1024]);
int mn_reference_disk(const uint8_t *rgba, int width, int height, double result[3], char error[1024]);
// Raw, unscaled FITS image planes, retaining BITPIX/BZERO/BSCALE and first usable HDU.
// Squeezed grayscale/RGB/RGBA image, in planar channel order. Alpha participates
// in display statistics; floating-point NaN/Inf are preserved, BLANK becomes NaN.
double *mn_read_fits(const char *path, int *width, int *height, int *channels, char error[1024]);
float *mn_read_npz(const char *path, int *rows, int *columns, double metadata[3], char error[1024]);
uint8_t *mn_zip_member(const char *path, const char *suffix, size_t *length, char error[1024]);
double *mn_gaussian_f64(const double *values, int width, int height, double sigma);
int mn_ellipse_outline(const double *points, int count, double *output, double center[2]);
// Lightness and filled, feathered illuminated coverage. Returned arrays have width*height elements.
uint8_t *mn_lightness(const uint8_t *photo, int width, int height, int channels, int *automatic_level, char error[1024]);
uint8_t *mn_coverage(const uint8_t *lightness, int width, int height, int threshold, char error[1024]);
double mn_correlation(const uint8_t *a, const uint8_t *b, const uint8_t *mask, int count);
int mn_dense_agreement(const uint8_t *reference, int rw, int rh, const uint8_t *photo, int pw, int ph,
                        int channels, const double matrix[6], const uint8_t *mask,
                        double result[2], char error[1024]);
// Validated physical view refinement. Geometry is updated only after spatial holdouts pass.
int mn_refine_view(const double geometry[13], const double matrix[6], const double *source,
                   const double *target, const double *surface_override, int count, int width, int height, double view_bound, int camera_only,
                   double updated_geometry[13], double updated_matrix[6], double evidence[6], char error[1024]);
int mn_eyepiece(const double geometry[13], const double projection[6], const double camera[6],
                const double *source, const double *target, int count, int rigid_inliers, double rigid_coverage,
                const uint8_t *photo, int width, int height, int channels, const uint8_t *mask,
                const double *limb, MNTask *task, double updated_geometry[13], double matrix[6],
                double distortion[4], double evidence[7], char error[1024]);
int mn_compact_field(const uint8_t *photo, int width, int height, int channels, const uint8_t *mask, int rectangle[4]);
int mn_eyepiece_edge_matches(const uint8_t *reference, int rw, int rh, const uint8_t *photo, int pw, int ph,
                            const uint8_t *mask, double maximum_distance, MNTask *task, MNMatch *result, char error[1024]);
// 1: independently validated refinement; 2: no material improvement; 0: rejected.
int mn_refine_eyepiece_edges(const double geometry[13], const double projection[6], const double camera[6],
                             const double lens[4], const double offsets[2], const double *source, const double *target,
                             int original_count, int count, const uint8_t *photo, int width, int height, const uint8_t *mask,
                             MNTask *task, double updated_geometry[13], double updated_matrix[6], double updated_lens[5],
                             double evidence[14], double folds[36], char error[1024]);
int mn_limb_pose(const uint8_t *reference, int size, const uint8_t *photo, int width, int height, int channels,
                 const uint8_t *mask, const double geometry[13], const double limb[5], MNTask *task,
                 double matrix[6], double evidence[2], char error[1024]);
int mn_photo_sun(const uint8_t *gray, const uint8_t *valid, const double *vectors, int width, int height, double sun[3]);
int mn_triangles(const double *points, const double *radii, const int *named, int feature_count,
                  const MNCandidate *candidates, int candidate_count, int width, int height,
                  const uint8_t *photo, int channels, const uint8_t *mask, MNTask *task,
                  MNMatch *result, double *score, char error[1024]);
#ifdef __cplusplus
}
#endif

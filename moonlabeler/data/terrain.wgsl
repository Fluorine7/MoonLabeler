// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 Fluorine Zhu
// Coarse LOLA slope/shadow model. Output: gray in bits 0..7, CPU repair in bit 8.
@group(0) @binding(0) var<storage, read> dem: array<f32>;
@group(0) @binding(1) var<storage, read> coords: array<f32>;
@group(0) @binding(2) var<storage, read> params: array<f32>;
@group(0) @binding(3) var<storage, read_write> result: array<u32>;
const INVALID: f32 = -1e30;
const RAD: f32 = 0.017453292519943295;

fn sample_grid(xbase: i32, ybase: i32, fraction: vec2<f32>) -> f32 {
    let rows = i32(params[0]); let cols = i32(params[1]);
    let delta = vec2<i32>(floor(fraction));
    var f = fraction-vec2<f32>(delta);
    var x0 = ((xbase+delta.x)%cols+cols)%cols;
    var y0 = ybase+delta.y;
    if (y0 < -1 || (y0 == -1 && f.y < .5) || y0 >= rows || (y0 == rows-1 && f.y > .5)) { return INVALID; }
    if (y0 < 0) { y0 = 0; f.y = 0; }
    if (y0 >= rows-1) { y0 = rows-1; f.y = 0; }
    let x1 = (x0+1)%cols; let y1 = min(y0+1, rows-1);
    return ((1-f.x)*(1-f.y)*dem[y0*cols+x0] + f.x*(1-f.y)*dem[y0*cols+x1]
         + (1-f.x)*f.y*dem[y1*cols+x0] + f.x*f.y*dem[y1*cols+x1])*params[5];
}
fn sample_height(lat: f32, lon: f32) -> f32 {
    var y = (params[2]-lat)*params[4]-.5;
    if (y < -.5 || y > params[0]-.5) { return INVALID; }
    let longitude = lon-params[3];
    let x = (longitude-360*floor(longitude/360))*params[4]-.5;
    y = clamp(y, 0, params[0]-1);
    return sample_grid(i32(floor(x)), i32(floor(y)), vec2<f32>(fract(x), fract(y)));
}
@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    let i = id.x;
    if (i >= u32(params[26])) { return; }
    let lat = coords[6*i]; let lon = coords[6*i+1];
    var repair = select(0u, 256u, abs(lat) > 89);
    let radius0 = params[6]; let ceiling = params[7];
    let sun = vec3<f32>(params[8], params[9], params[10]);
    let observer = vec3<f32>(params[11], params[12], params[13]);
    let a = lat*RAD; let b = lon*RAD;
    let radial = vec3<f32>(cos(a)*cos(b), cos(a)*sin(b), sin(a));
    let xbase = i32(coords[6*i+2]); let ybase = i32(coords[6*i+3]);
    let f = vec2<f32>(coords[6*i+4], coords[6*i+5]);
    let height = sample_grid(xbase, ybase, f);
    let hn = sample_grid(xbase, ybase, f+vec2<f32>(0, -.5));
    let hs = sample_grid(xbase, ybase, f+vec2<f32>(0, .5));
    let he = sample_grid(xbase, ybase, f+vec2<f32>(.5, 0));
    let hw = sample_grid(xbase, ybase, f+vec2<f32>(-.5, 0));
    if (min(min(min(hn, hs), min(he, hw)), height) == INVALID) { result[i] = repair; return; }
    let step = .5/params[4];
    let vertical = (hn-hs)/(2*step*RAD*radius0);
    let horizontal = (he-hw)/(2*step*RAD*radius0*max(cos(a), 1e-6));
    let east = vec3<f32>(-sin(b), cos(b), 0);
    let northward = vec3<f32>(-sin(a)*cos(b), -sin(a)*sin(b), cos(a));
    let normal = normalize(radial-horizontal*east-vertical*northward);
    let sun_dot = dot(normal, sun); let view_dot = dot(normal, observer);
    let incidence = max(sun_dot, 0); let emission = max(view_dot, 0);
    if (abs(sun_dot) < 1e-5 || abs(view_dot) < 1e-5) { repair = 256u; }
    if (incidence <= 0 || emission <= 0) { result[i] = repair; return; }
    let position = radial*(radius0+height);
    let along_sun = dot(position, sun); let sun_squared = dot(sun, sun);
    for (var j = 0u; j < 12u; j++) {
        let distance = params[14+j];
        let ray = position+distance*sun;
        let radius = length(ray);
        if (abs(radius-ceiling) < .004) { repair = 256u; }
        if (radius >= ceiling && along_sun+distance*sun_squared >= 0) { break; }
        let ray_lat = asin(clamp(ray.z/radius, -1, 1))/RAD;
        let ray_lon = atan2(ray.y, ray.x)/RAD;
        let terrain = radius0+sample_height(ray_lat, ray_lon);
        if (abs(radius-terrain+1e-4) < .004) { repair = 256u; }
        if (radius < terrain-1e-4) { result[i] = repair; return; }
    }
    let ratio = 2*incidence/(incidence+emission+1e-8);
    let light = sqrt(clamp(ratio, 0, 1));
    let brightness = light*220;
    if ((light < 1 && abs(brightness-round(brightness)) < .02) || abs(ratio-1) < 1e-5) { repair = 256u; }
    result[i] = u32(brightness) | repair;
}

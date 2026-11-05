#!/bin/bash
set -euo pipefail
swift_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_root="$(dirname "$swift_root")"
resources="$swift_root/Sources/MoonCore/Resources"
mkdir -p "$resources"
stage() {
    local name="$1" cache="$2" url="$3"
    if [ ! -f "$resources/$name" ]; then
        if [ -f "$cache/$name" ]; then cp "$cache/$name" "$resources/$name"
        else
            curl --fail --location --retry 2 --max-time 300 --silent --show-error "$url" -o "$resources/$name.partial"
            mv "$resources/$name.partial" "$resources/$name"
        fi
    fi
}
stage de421.bsp "$repo_root/.cache/ephemeris" https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp
stage moon_080317.tf "$repo_root/.cache/ephemeris" https://naif.jpl.nasa.gov/pub/naif/generic_kernels/fk/satellites/moon_080317.tf
stage pck00008.tpc "$repo_root/.cache/ephemeris" https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/a_old_versions/pck00008.tpc
stage moon_pa_de421_1900-2050.bpc "$repo_root/.cache/ephemeris" https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/moon_pa_de421_1900-2050.bpc
stage naif0012.tls "$swift_root/.build/native-deps" https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls
if [ "${MOON_BUNDLE_DEM:-1}" == 1 ]; then
    stage LDEM_16.LBL "$repo_root/.cache/terrain" https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/IMG/LDEM_16.LBL
    stage LDEM_16.IMG "$repo_root/.cache/terrain" https://imbrium.mit.edu/DATA/LOLA_GDR/CYLINDRICAL/IMG/LDEM_16.IMG
fi

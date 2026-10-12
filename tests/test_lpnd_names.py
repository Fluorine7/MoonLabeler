# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from copy import deepcopy
import json

from moonlabeler.sources import PACKAGE_DATA, translate_catalog, feature_search_text


def test_lpnd_overrides_legacy_cache_but_preserves_search_and_coordinates():
    feature = {'name': 'Clavius', 'name_zh': '克拉维乌斯', 'id': '123',
               'lat': -58.4, 'lon': -14.4, 'diameter': 230,
               'name_zh_source': 'https://nadc.china-vo.org/old', 'name_zh_derived': True}
    before = deepcopy(feature)
    translate_catalog([feature])
    assert feature['name_zh'] == '克拉维斯'
    assert 'lpnd.bao.ac.cn' in feature['name_zh_source']
    assert feature['name_zh_term'] == '克拉维斯坑'
    assert 'name_zh_derived' not in feature
    assert '克拉维乌斯' in feature_search_text(feature)
    for field in ('id', 'lat', 'lon', 'diameter'):
        assert feature[field] == before[field]
    once = deepcopy(feature)
    translate_catalog([feature])
    assert feature == once


def test_satellite_captions_keep_original_authority_terms():
    features = [{'name': name} for name in ('Copernicus D', 'Hadley C', 'Alpes A', 'Clavius D')]
    translate_catalog(features)
    assert [f['name_zh'] for f in features] == ['哥白尼 D', '哈得来 C', '阿尔卑斯 A', '克拉维斯 D']
    assert features[1]['name_zh_term'] == '[哈得来坑]C坑'
    assert '克拉维乌斯 D' in feature_search_text(features[3])
    assert not any(f.get('name_zh_derived') for f in features)


def test_manual_additions_and_fallback_are_not_attributed_to_lpnd():
    features = [{'name': name} for name in ('Liu Hui', 'Mons Latreille', 'Planitia Descensus', 'Unknown A')]
    translate_catalog(features)
    assert features[0]['name_zh_source_name'] == '中国人名'
    assert features[0]['name_zh_source'] == ''
    assert features[1]['name_zh_source_name'] == 'NADC 天文学名词'
    assert 'nadc.china-vo.org' in features[2]['name_zh_source']
    assert not features[3].get('name_zh')


def test_all_supplied_entries_load_offline_without_changing_original_terms():
    names = json.loads((PACKAGE_DATA/'lunar_chinese_names.json').read_text())['names']
    features = [{'name': name} for name in names]
    translate_catalog(features)
    assert len(features) == 9040
    assert sum(v['source'].startswith('LPND') for v in names.values()) == 9031
    for feature in features:
        original = names[feature['name']]
        assert feature['name_zh']
        assert feature['name_zh_term'] == original.get('term_zh', original['zh'])
        if original['source'].startswith('LPND'):
            assert feature['name_zh_source'].startswith('https://lpnd.bao.ac.cn/')


def test_unlisted_satellite_inherits_primary_translation_with_derived_flag():
    feature = {'name': 'Clavius Z'}
    # Z is not an explicitly translated Clavius satellite in the supplied snapshot.
    names = json.loads((PACKAGE_DATA/'lunar_chinese_names.json').read_text())['names']
    assert feature['name'] not in names
    translate_catalog([feature])
    assert feature['name_zh'] == '克拉维斯 Z'
    assert feature['name_zh_derived'] is True

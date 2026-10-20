# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Fluorine Zhu
from copy import deepcopy
import json

from moonlabeler.sources import PACKAGE_DATA, translate_catalog, feature_search_text


def test_mixed_snapshot_keeps_lpnd_as_the_chinese_name_authority(monkeypatch):
    from moonlabeler import sources
    primary, legacy = sources._translation_tables(PACKAGE_DATA)
    primary = dict(primary, source_urls=['https://planetarynames.wr.usgs.gov/Page/MOON/target',
                                        'https://lpnd.bao.ac.cn/#/search?is=1',
                                        'https://www.ap-i.net/avl/en/start'])
    monkeypatch.setattr(sources, '_translation_tables', lambda directory: (primary, legacy))
    feature = {'name': 'Clavius'}
    translate_catalog([feature])
    assert feature['name_zh'] == '克拉维斯'
    assert feature['name_zh_source'] == 'https://lpnd.bao.ac.cn/#/search?is=1'


def test_english_placeholders_allow_legacy_and_parent_translations(monkeypatch):
    from moonlabeler import sources
    primary = dict(source='Mixed nomenclature', source_urls=['https://lpnd.bao.ac.cn/'], names={
        'Example': {'zh': 'Example'}, 'Parent': {'zh': '主坑', 'source': 'LPND'},
        'Parent A': {'zh': 'Parent A'}, 'Untranslated': {'zh': 'Untranslated'}})
    legacy = dict(source='Legacy terms', names={
        'Example': {'zh': '已有译名', 'url': 'https://example.org/term'}})
    monkeypatch.setattr(sources, '_translation_tables', lambda directory: (primary, legacy))
    features = [{'name': name} for name in ('Example', 'Parent A', 'Untranslated')]
    translate_catalog(features)
    assert features[0]['name_zh'] == '已有译名'
    assert features[0]['name_zh_source'] == 'https://example.org/term'
    assert features[1]['name_zh'] == '主坑 A' and features[1]['name_zh_derived'] is True
    assert not features[2].get('name_zh')
    assert not features[2].get('name_zh_source_name')
    assert feature_search_text(features[2]).strip() == 'Untranslated'


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
    snapshot = json.loads((PACKAGE_DATA/'lunar_chinese_names.json').read_text(encoding="utf-8"))
    names = snapshot['names']
    features = [{'name': name} for name in names]
    translate_catalog(features)
    assert len(features) == snapshot['count'] == 10431
    assert sum(v.get('source', '').startswith('LPND') for v in names.values()) == 9031
    assert sum(bool(f.get('name_zh')) for f in features) == 9040
    for feature in features:
        original = names[feature['name']]
        if original['zh'] == feature['name']:
            assert not feature.get('name_zh'), 'An English placeholder is not a translated caption'
            assert not feature.get('name_zh_source_name')
            continue
        assert feature['name_zh']
        assert feature['name_zh_term'] == original.get('term_zh', original['zh'])
        if original.get('source', '').startswith('LPND'):
            assert feature['name_zh_source'].startswith('https://lpnd.bao.ac.cn/')


def test_expanded_snapshot_does_not_replace_active_catalogue_geometry():
    features = json.loads((PACKAGE_DATA/'catalog.json').read_text(encoding="utf-8"))['features']
    before = deepcopy(features)
    translate_catalog(features)
    assert len(features) == 9087
    assert sum(bool(f.get('name_zh')) for f in features) == 9042
    for feature, original in zip(features, before):
        for key in ('id', 'name', 'lat', 'lon', 'diameter', 'kind', 'approved'):
            assert feature.get(key) == original.get(key)
    assert not any(f['name'] == 'APOLLO 11 BASE' for f in features)


def test_unlisted_satellite_inherits_primary_translation_with_derived_flag():
    feature = {'name': 'Clavius Z'}
    # Z is not an explicitly translated Clavius satellite in the supplied snapshot.
    names = json.loads((PACKAGE_DATA/'lunar_chinese_names.json').read_text(encoding="utf-8"))['names']
    assert feature['name'] not in names
    translate_catalog([feature])
    assert feature['name_zh'] == '克拉维斯 Z'
    assert feature['name_zh_derived'] is True

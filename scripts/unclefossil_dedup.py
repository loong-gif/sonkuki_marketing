"""Strict, auditable one-to-one deduplication for the Uncle Fossil export.

The verification snapshot below was collected on 2026-08-12 from public
Uncle Fossil product pages: Firecrawl was used first and egolite completed
the pages that Firecrawl rate-limited or could not load.  The script never
changes the downloaded source CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlparse


BASE_URL = "https://www.unclefossil.com/"
SOURCE_FIELDS = [
    "parent_sku",
    "parent_name",
    "parent_price",
    "name",
    "price",
    "volume(ml)",
    "provider",
    "url",
]
REVIEW_FIELDS = [
    "row_id",
    *SOURCE_FIELDS,
    "group_key",
    "identity_key",
    "source_sku_collision",
    "selected",
    "decision",
    "decision_reason",
    "verification_method",
    "page_title",
    "page_evidence",
]

GENERIC_TOKENS = {
    "sake",
    "liquor",
    "chinese",
    "baijiu",
    "junmai",
    "ginjo",
    "daiginjo",
    "premium",
    "collection",
    "limited",
    "edition",
    "gift",
    "set",
    "bottle",
    "bottles",
    "spirits",
    "wine",
    "wholesale",
    "delivery",
    "free",
    "price",
    "prices",
    "ml",
}
VARIANT_TERMS = {
    "aquarius",
    "aries",
    "cancer",
    "capricorn",
    "leo",
    "pisces",
    "sagittarius",
    "virgo",
    "nigori",
    "dry",
    "golden",
    "white",
    "black",
}
ALIASES = {
    "tamanohikari": "tamano hikari",
    "tamanohikari": "tamano hikari",
    "wuliangye": "wu liang ye",
    "guijiu": "gui jiu",
    "jiuzudukang": "jiuzu dukang",
    "jiuzudukang": "jiuzu dukang",
    "fenchiew": "fen chiew",
    "honghualang": "hong hua lang",
    "gujinggongjiu": "gu jing gong",
    "hengshuilaobaigan": "heng shui lao bai gan",
    "guojiao": "guo jiao",
    "shuijingfang": "shui jing fang",
    "yanghe": "yang he",
    "luzhoulaojiao": "luzhou lao jiao",
    "zishadaqu": "zisha daqu",
    "mianrou": "mian rou",
    "dukang": "du kang",
    "manjyu": "manju",
    "tokubetsu": "toku",
    "oceanic blue": "hai zhi lan",
    "moutai": "moutai",
    "kweichow": "moutai",
}

# These terms identify a producer or umbrella label, rather than the product
# itself.  A match on one of them alone is insufficient in strict mode (for
# example, Moutai Bulaojiu must never match Moutai 15Yr merely because both
# names contain "Moutai").
BRAND_TOKENS = {
    "moutai",
    "kweichow",
    "dassai",
    "kubota",
    "wuliangye",
    "shui",
    "jing",
    "fang",
}


def _url_path(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path.lstrip("/")


# Titles observed from Uncle Fossil PDPs and listing pages via egolite.
# The first two pages were also independently retrievable through Firecrawl.
PAGE_TITLES = {
    "asahi-shuzo-niigata-senshin-junmai-daiginjo-18l.html": "Asahi Shuzo (Niigata) Senshin Junmai 洗心 Daiginjo 1.8L $239 FREE DELIVE",
    "kikuhime-by-daiginjo-sake-by-720ml.html": "Kikuhime B.Y. Daiginjo Sake 菊姬 大吟酿 720ml $159 FREE DELIVERY",
    "tamanohikari-tokusen-junmai-ginjo-180ml.html": "Tamanohikari Tokusen Junmai Ginjo 180ml 玉乃光 $6",
    "foo-fighters-hansho-silver-junmai-daiginjo-720ml.html": "Foo Fighters Hansho Silver Junmai Daiginjo 720ml $43",
    "suigei-harmony-blend-junmai-daiginjo-720ml.html": "Suigei Harmony Blend Junmai Daiginjo 720ml $23",
    "dassai-50-sake-720ml.html": "Dassai 45 Sake 720ml $28",
    "tatsuriki-junmai-ginjo-shinryu-nishiki-720ml.html": "Tatsuriki Junmai Ginjo Shinryu Nishiki 720ml 龍力纯米吟酿 神龍錦 $39",
    "brands/tatsuriki/": "Tatsuriki",
    "nito-yamadanishiki-65-junmai-720ml.html": "Nito Yamadanishiki 65 Junmai 二兔 720ml $38",
    "shichida-fall-seasonal-ltd-aiyama-75-sake-junmai-7.html": "Shichida Fall Seasonal LTD Aiyama 75 Sake Junmai 720ml 七田 愛山 纯米 $45",
    "okunomatsu-junmai-sake-720ml.html": "Okunomatsu Junmai Sake 720ml $27",
    "tamagawa-aged-four-years-junmai-daiginjo-heart-of.html": "Tamagawa Aged Four Years Junmai Daiginjo Heart of the Sun 720ml $81",
    "tenzan-shuzo-shichida-parfait-junmai-daiginjo-720m.html": "Tenzan Shuzo Shichida Parfait Junmai Daiginjo 720ml $359",
    "yushan-taiwan-original-cellar-kaoliang-6years-700m.html": "Yushan Taiwan Original Cellar Kaoliang 6Years 台湾玉山六年陈原窖高粱 $49",
    "search/834/": "Search results for 834",
    "kinmen-kaoliang-premium-black-750-ml.html": "Kinmen Kaoliang Premium Black Baijiu 金门高粱 金酒典藏珍品黑金龙 $63",
    "search/47194/": "Search results for 47194",
    "luzhoulaojiao-erqu-750ml.html": "LuZhouLaoJiao ErQu 泸州老窖二曲 $21",
    "confucius-faily-750ml.html": "Confucius Family 孔府家酒新陶 Kongfuji 750ml $36",
    "wing-lee-wai-hong-kong-ng-ka-py-liquor-750ml.html": "Wing Lee Wai Hong Kong Ng Ka Py Liquor 永利威双鸭牌五加皮 750ml $35",
    "spirits-liquor/baijiu-spirits/": "中国白酒全美最低批发价 Spirits Sake Baijiu",
    "spirits-liquor/baijiu-spirits/page4.html": "中国白酒全美最低批发价 Spirits Sake Baijiu",
    "spirits-liquor/baijiu-spirits/page13.html": "中国白酒全美最低批发价 Spirits Sake Baijiu",
    "wuliangye-2021-750ml.html": "WuLiangYe 五粮液长城装 750ml $152",
    "shede-tun-zhi-hu-black-chinese-baijiu-750ml.html": "Shede Tun Zhi Hu (Black) Chinese Baijiu 舍得吞之乎黑金酱香型白酒 750ml $170",
    "shede-classic-chinese-baijiu-375ml.html": "Shede Classic Chinese Baijiu 舍得浓香型白酒 375ml $41",
    "shede10-yrs-collection-chinese-baijiu-375ml.html": "Shede10 yrs Collection Chinese Baijiu 375ml 舍得藏品十年白酒 $121",
    "tang-gou-tequ-porcelain-bottle-chinese-baijiu-500m.html": "Tang Gou Tequ Porcelain bottle Chinese Baijiu 500ml 汤沟瓷瓶特曲 $41",
    "shede-2025-the-year-of-snake-collection-chinese-ba.html": "Shede 2025 The Year Of Snake Collection Chinese Baijiu 舍得蛇年生肖酒 $62",
    "search/359": "Search results for 359",
    "moutai-15yr-375ml.html": "Moutai 15Yr 茅台15年 375ml $1899",
    "guojiao-750ml.html": "GuoJiao 国窖中国品味 $419",
    "moutai-chun-leo-375ml.html": "Moutai Chun Leo 茅台醇 狮子座 375ml $42",
    "search/ngh/": "Search results for ngh",
    "search/383/": "Search results for 383",
    "premium-fen-chiew-silk-road-limited-edition-750ml.html": "Premium Fen Chiew (Silk Road Limited Edition) 汾酒 丝绸之路限量版 $312",
    "guizhou-guijiu-5years-375ml.html": "Guizhou Guijiu 5Years 375ml 贵州贵酒酱香型五年白酒 $36",
    "guizhou-guijiu-30years-375ml.html": "Guizhou Guijiu 30Years 375ml 贵州贵酒酱香型三十年白酒 $229",
    "search/334": "Search results for 334",
    "hua-du-jin-cai-1l.html": "Hua Du Jin Cai 华都金彩 天安门 1L $79",
    "moutai-bulaojiu-125ml3-gift-set.html": "Moutai Bulaojiu 茅台不老酒 礼品装 125ml*3 Gift Set $167",
    "moutai-chun-aquarius-375ml.html": "Moutai Chun Aquarius 茅台醇 水瓶座 375ml $42",
    "moutai-chun-aries-375ml.html": "Moutai Chun Aries 茅台醇 白羊座 375ml $64",
    "kweichow-moutai-50ml-2-bottles-per-set.html": "Kweichow Moutai 50ml 贵州飞天茅台两瓶装 2 bottles Per Set $91",
    "moutai-day-in-san-francisco-gold-375ml.html": "Moutai Day In San Francisco Gold 贵州茅台旧金山纪念版金 375ml $1999",
    "moutai-200ml-2018.html": "Moutai 贵州茅台 200ml 2018 $503",
    "moutai-chun-sagittarius-375ml.html": "Moutai Chun Sagittarius 茅台醇 射手座 375ml $65",
    "moutai-15yr-15-2018-375ml.html": "Moutai 15Yr 茅台15年 2018 375ml $2209",
    "jiuzu-dukang-yingbin-red-500ml.html": "JiuZu DuKang Yingbin Red 500ml 杜康迎宾酒 $39",
    "jiuzu-dukang-collection-15ys-500ml50ml.html": "JiuZu DuKang Collection 15Ys 500ml+50ml 酒祖杜康馆藏十五年 $169",
    "dukang-hongyundangtou-750ml.html": "DuKang Hongyundangtou 750ml 杜康红运当头 $19",
    "tanzawasan-yamahai-rinho-cold-mountain-junmai-sake.html": "404 Page not found",
    "tomio-all-kyoto-300ml.html": "Tomio All Kyoto 300ml 富翁 $15",
    "jiuzudukang-red-12-375ml.html": "JiuZuDuKang Red 酒祖杜康 12窖 红盒 375ml $55",
    "search/935/page3.html": "Search results for 935",
    "du-kang-xiao-feng-tan-2-375ml-2-bottles.html": "Du Kang Xiao Feng Tan 375ml 2 bottles 酒祖杜康小封坛 2瓶套装 $480",
    "jiuzu-dukang-xiao-feng-tan-375ml.html": "JiuZu DuKang Xiao Feng Tan 酒祖杜康小封坛 375ml $99",
    "jinsha-gu-jiu-5-blue-box375ml.html": "Jinsha Gu Jiu Diamond Star Series 5 Star 金沙古酒 5星 375ml $45",
    "moutai-prince-classics-twin-pack-500ml-x-2.html": "Moutai Prince Classics (Twin Pack) 500ml X 2 茅台王子酒两瓶装 $179",
    "moutai-golden-prince-twin-pack-500ml-x-2.html": "Moutai Golden Prince (Twin Pack) 500ml X 2 茅台金王子酒两瓶装 $133",
    "dassai-blue-type-50-junmai-daiginjo-nigori-sake-37.html": "Dassai Blue Type 50 Junmai Daiginjo Nigori Sake 375ml $18",
    "dassai-blue-type-50-dry-junmai-daiginjo-sake-375ml.html": "Dassai Blue Type 50 Dry Junmai Daiginjo Sake 375ml 獭祭蓝色系列纯米大吟釀 $14",
}

# Canonical product URLs verified from the title snapshot.  A None value means
# strict mode deliberately exports no row for that parent identity.
VERIFIED_CANONICALS = {
    "Kubota - Seppou Black Snow Peak Yamahai Junmai Daiginjo 500ml 久保田 黑雪峰 山廢 純米大吟釀": "kubota-seppou-500ml-30883303.html",
    "Kubota - Senshin Junmai Daiginjo 1.8L 久保田 洗心 純米大吟釀": "asahi-shuzo-niigata-senshin-junmai-daiginjo-18l.html",
    "Tamano Hikari - Tokusen Junmai Ginjo 180ml 玉乃光 特選 純米吟醸": "tamanohikari-tokusen-junmai-ginjo-180ml.html",
    "Suigei - Harmony Junmai Daiginjo 720ml 酔鯨 純米大吟醸": "suigei-harmony-blend-junmai-daiginjo-720ml.html",
    "Tatsuriki - Shinryu Nishiki Junmai Ginjo 720ml 龍力 神龍錦 純米吟釀": "tatsuriki-junmai-ginjo-shinryu-nishiki-720ml.html",
    "Shichida Fall Seasonal LTD Aiyama 75 Sake Junmai 720ml 七田愛山纯米": "shichida-fall-seasonal-ltd-aiyama-75-sake-junmai-7.html",
    "Shichida - Parfait Junmai Daiginjo 720ml 七田 純米大吟釀": "tenzan-shuzo-shichida-parfait-junmai-daiginjo-720m.html",
    "Yushan - Taiwan Original Cellar Kaoliang Liquor 6Yrs 700ml 玉山台湾原窖 六年陈高粱酒": "yushan-taiwan-original-cellar-kaoliang-6years-700m.html",
    "Kinmen Kaoliang - Premium Black 56% Taiwan Kaoliang 750ml 金门高梁 金门高梁 金酒典藏珍品 五十六度": "kinmen-kaoliang-premium-black-750-ml.html",
    "Confucius Family - Chinese Baijiu 750ml 孔府家酒 新陶": "confucius-faily-750ml.html",
    "WuLiangYe - Great Wall Edition Chinese Baijiu 750ml 五粮液 长城装": "wuliangye-2021-750ml.html",
    "Shede Tun Zhi Hu Chinese Baijiu 750ml 舍得吞之乎": "shede-tun-zhi-hu-black-chinese-baijiu-750ml.html",
    "Shede 10Yrs Collection Chinese Baijiu 375ml 舍得十年珍藏": "shede10-yrs-collection-chinese-baijiu-375ml.html",
    "Shede 2025 The Year Of Snake Collection Chinese Baijiu 375ml 舍得蛇年限定版": "shede-2025-the-year-of-snake-collection-chinese-ba.html",
    "GuoJiao 1573 - The Taste of China Chinese Baijiu 750ml 国窖1573 中国品味": "guojiao-750ml.html",
    "Fen Chiew - Silk Road Limited Edition Premium Chinese Baijiu 750ml 汾酒 丝绸之路限定版": "premium-fen-chiew-silk-road-limited-edition-750ml.html",
    "Guizhou Gui Jiu - Chinese Baijiu 30 Years 375ml 贵州贵酒 三十年": "guizhou-guijiu-30years-375ml.html",
    "Guizhou Gui Jiu - Chinese Baijiu 5 Years 375ml 贵州贵酒 五年": "guizhou-guijiu-5years-375ml.html",
    "Hua Du Jin Cai Tian An Men Chinese Baijiu 1L 华都金彩天安门酒": "hua-du-jin-cai-1l.html",
    "Kweichow Moutai - Bulaojiu Premium Gift Set 125ml*3 贵州茅台 不老酒珍品礼盒装": "moutai-bulaojiu-125ml3-gift-set.html",
    "Kweichow Moutai - Moutai Chun Aquarius Chinese Baijiu 375ml 贵州茅台 茅台醇水瓶座": "moutai-chun-aquarius-375ml.html",
    "Kweichow Moutai - Moutai Chun Aries Chinese Baijiu 375ml 贵州茅台 茅台醇白羊座": "moutai-chun-aries-375ml.html",
    "Kweichow Moutai - Moutai Chun Cancer Chinese Baijiu 375ml 贵州茅台 茅台醇巨蟹座": None,
    "Kweichow Moutai - Moutai Chun Capricorn Chinese Baijiu 375ml 贵州茅台 茅台醇摩羯座": None,
    "Kweichow Moutai - Moutai Chun Leo Chinese Baijiu 375ml 贵州茅台 茅台醇狮子座": "moutai-chun-leo-375ml.html",
    "Kweichow Moutai - Moutai Chun Pisces Chinese Baijiu 375ml 贵州茅台 茅台醇双鱼座": None,
    "Kweichow Moutai - Moutai Chun Sagittarius Chinese Baijiu 375ml 贵州茅台 茅台醇射手座": "moutai-chun-sagittarius-375ml.html",
    "Kweichow Moutai - Moutai Chun Virgo Chinese Baijiu 375ml 贵州茅台 茅台醇处女座": None,
    "DuKang Hong yun dang tou Chinese Baijiu 750ml 杜康红运当头白酒": "dukang-hongyundangtou-750ml.html",
    "Tanzawasan Yamahai Rinho Cold Mountain Junmai Sake 720ml 丹泽山山廃純米酒": None,
    "Tomio - All Kyoto Rice Junmai Ginjo 300ml 富翁 全量京都産米 純米吟醸": "tomio-all-kyoto-300ml.html",
    "Jiuzu Dukang - 12 Cellar Red 40 Years of Cellar Age Chinese Baijiu 375ml 酒祖杜康 十二区四十年窖龄": "jiuzudukang-red-12-375ml.html",
    "JiuZu DuKang Xiao Feng Tan Chinese Baijiu 375ml 酒祖杜康小封坛酒": "jiuzu-dukang-xiao-feng-tan-375ml.html",
    "Jinsha Gu Jiu - Diamond Star Series 5 Star Chinese Baijiu 375ml 金沙古酒 五星": "jinsha-gu-jiu-5-blue-box375ml.html",
    "Kweichow Moutai - Prince Classics Chinese Baijiu (Twin Pack) 500ml X 2 贵州茅台 王子酒": "moutai-prince-classics-twin-pack-500ml-x-2.html",
    "Dassai Blue - Type 50 Junmai Daiginjo 375ml 獭祭蓝色系列50 純米大吟釀": None,
    # New rows accepted only after page-title verification.  They remain
    # explicit because the retailer omits descriptive source terms such as
    # "Nigori" or uses a legacy slug (the 45/720 page below).
    "Dassai - 45 Nigori Sparkling Junmai Daiginjo 360ml 獭祭45 純米大吟釀 氣泡濁り酒": "dassai-sparkling-45-junmai-daiginjo-sake-45-360ml.html",
    "Dassai - 45 Junmai Daiginjo 720ml 獭祭45 純米大吟釀": "dassai-50-sake-720ml.html",
    "Dassai - 45 Junmai Daiginjo 1.8L 獭祭45 純米大吟釀": "dassai-45-junmai-daiginjo-sake-18l.html",
    "Dassai - 39 Junmai Daiginjo 720ml 獭祭39 純米大吟釀": "dassai-39-junmai-daiginjo-sake-720ml.html",
    "Dassai - 39 Junmai Daiginjo 300ml 獭祭39 純米大吟釀": "dassai-39-junmai-daiginjo-sake-300ml.html",
    "Dassai - 23 Junmai Daiginjo 720ml 獭祭23 純米大吟釀": "dassai-23-sake-720ml.html",
    "Dassai - 23 Junmai Daiginjo 300ml 獭祭23 純米大吟釀": "dassai-23-junmai-daiginjo-sake-300ml-61270604.html",
    "Dassai - 23 Junmai Daiginjo 1.8L 獭祭23 純米大吟釀": "dassai-23-junmai-daiginjo-sake-18l.html",
    "Kweichow Moutai - Premium Chinese Baijiu 500ml 贵州茅台 精品酒": "kweichow-moutai-premium-500ml.html",
    # New source rows that the 2026-08-12 title snapshot cannot identify
    # uniquely.  They stay in the audit CSV but must not enter the main CSV.
    "Kubota - Seppou White Snow Peak Soujo Junmai Daiginjo 500ml 久保田 白雪峰 爽醸 純米大吟釀": None,
    "Shui Jing Fang - Wellbay Jing Tai Chinese Baijiu 750ml 水井坊 井台": None,
    "Yanghe - Dream Blue M6+ 375ml 洋河 梦之蓝 梦六升级版": None,
    "Niu Lan Shan Zhen Pin 20Yrs Chen Niang Chinese Baijiu 1L 北京牛栏山二锅头珍品二十年陈": None,
}


def normalise(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    for source, replacement in ALIASES.items():
        text = text.replace(source, replacement)
    text = re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", text)
    return " ".join(text.split())


def parse_volume_ml(value: str) -> int | None:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(ml|l)\b", (value or "").lower())
    if not match:
        return None
    amount = float(match.group(1))
    return round(amount * 1000) if match.group(2) == "l" else round(amount)


def group_key(row: Mapping[str, str]) -> str:
    sku = (row.get("parent_sku") or "").strip()
    if sku:
        return f"sku:{sku}"
    parent_name = normalise(row.get("parent_name", ""))
    volume = parse_volume_ml(row.get("parent_name", "")) or parse_volume_ml(row.get("parent_volume", ""))
    return f"name:{parent_name}|volume:{volume or ''}ml"


def identity_key(row: Mapping[str, str]) -> str:
    sku = (row.get("parent_sku") or "").strip()
    parent_name = normalise(row.get("parent_name", ""))
    # Candidate volume may itself be wrong, so it must never split one parent
    # identity into multiple groups.  `parent_volume` exists in unit fixtures;
    # the production export carries its parent volume in `parent_name`.
    volume = parse_volume_ml(row.get("parent_name", "")) or parse_volume_ml(row.get("parent_volume", ""))
    prefix = f"sku:{sku}" if sku else "sku:blank"
    return f"{prefix}|name:{parent_name}|volume:{volume or ''}ml"


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z]+|\d+|[\u3400-\u9fff]+", normalise(value))
        if token not in GENERIC_TOKENS and len(token) > 1
    }


def _identity_name_tokens(value: str) -> set[str]:
    """Use the source's English product identity when present.

    Chinese product descriptors often vary between a supplier export and the
    retailer title (for example, a style description replaces ``经典``).  They
    should not invalidate an otherwise exact English product title.  For an
    all-Chinese name, retain its CJK token as the strict matching signal.
    """
    normalised = normalise(value)
    english = {
        token
        for token in re.findall(r"[a-z]+", normalised)
        if token not in GENERIC_TOKENS and len(token) > 1
    }
    if english:
        return english
    return {
        token
        for token in re.findall(r"[\u3400-\u9fff]+", normalised)
        if token not in GENERIC_TOKENS
    }


def _is_listing_url(url: str) -> bool:
    path = urlparse(url).path.lower().rstrip("/")
    return (
        path == "/search"
        or path.startswith("/search/")
        or path.startswith("/brands/")
        or path.startswith("/collections/")
        or path.startswith("/spirits-liquor/")
    )


def assess_candidate(
    parent_name: str,
    candidate_name: str,
    candidate_volume: str,
    url: str,
    page_title: str,
) -> dict[str, str]:
    """Return an auditable accept/reject/review judgement for one candidate."""
    if _is_listing_url(url):
        return {"action": "reject", "reason": "listing_url", "evidence": "search, brand, or category page"}
    if not page_title.strip():
        return {"action": "review", "reason": "missing_page_title", "evidence": "no page title available"}
    if "page not found" in page_title.lower() or re.fullmatch(r"uncle fossil wine.?spirits", page_title.strip(), re.I):
        return {"action": "reject", "reason": "page_not_found", "evidence": page_title}

    parent_tokens = _tokens(parent_name)
    page_tokens = _tokens(page_title)
    parent_name_tokens = _identity_name_tokens(parent_name)
    page_name_tokens = _identity_name_tokens(page_title)
    shared_name_tokens = parent_name_tokens & page_name_tokens
    specific_shared_tokens = shared_name_tokens - BRAND_TOKENS
    parent_variants = VARIANT_TERMS & parent_tokens
    page_variants = VARIANT_TERMS & page_tokens
    if not specific_shared_tokens:
        return {
            "action": "reject",
            "reason": "name_mismatch",
            "evidence": (
                "no shared product-identity token; shared producer token(s): "
                f"{', '.join(sorted(shared_name_tokens)) or 'none'}"
            ),
        }
    if page_variants != parent_variants:
        return {
            "action": "reject",
            "reason": "variant_mismatch",
            "evidence": f"parent={', '.join(sorted(parent_variants)) or 'none'}; page={', '.join(sorted(page_variants)) or 'none'}",
        }

    expected_volume = parse_volume_ml(parent_name)
    observed_volume = parse_volume_ml(page_title) or parse_volume_ml(candidate_name) or parse_volume_ml(candidate_volume)
    if expected_volume and observed_volume and expected_volume != observed_volume:
        return {
            "action": "reject",
            "reason": "volume_mismatch",
            "evidence": f"parent={expected_volume}ml page={observed_volume}ml",
        }

    return {"action": "accept", "reason": "title_match", "evidence": page_title}


def _best_row(rows: Iterable[dict[str, str]], parent_name: str) -> dict[str, str]:
    def quality(row: dict[str, str]) -> tuple[int, int]:
        overlap = len(_tokens(parent_name) & _tokens(row.get("name", "")))
        return overlap, -int(row["row_id"])

    return max(rows, key=quality)


def _review_row(
    row: dict[str, str],
    sku_collision: bool,
    selected: bool,
    decision: str,
    reason: str,
    method: str,
    title: str,
) -> dict[str, str | bool]:
    evidence = title or "No title snapshot was required for an identical-URL collapse."
    return {
        "row_id": row["row_id"],
        **{field: row.get(field, "") for field in SOURCE_FIELDS},
        "group_key": group_key(row),
        "identity_key": identity_key(row),
        "source_sku_collision": sku_collision,
        "selected": selected,
        "decision": decision,
        "decision_reason": reason,
        "verification_method": method,
        "page_title": title,
        "page_evidence": evidence,
    }


def validate_outputs(
    cleaned_rows: Iterable[Mapping[str, object]],
    review_rows: Iterable[Mapping[str, object]],
    source_rows: Iterable[Mapping[str, object]],
) -> None:
    cleaned = list(cleaned_rows)
    review = list(review_rows)
    source = list(source_rows)
    source_ids = [str(row["row_id"]) for row in source]
    review_ids = [str(row["row_id"]) for row in review]
    if len(review_ids) != len(source_ids) or set(review_ids) != set(source_ids):
        raise ValueError("review conservation failed")
    selected_ids = {str(row["row_id"]) for row in review if row.get("selected") is True}
    cleaned_ids = {str(row["row_id"]) for row in cleaned}
    if selected_ids != cleaned_ids:
        raise ValueError("selected review rows do not equal cleaned rows")
    keys = [str(row.get("identity_key") or identity_key(row)) for row in cleaned]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate cleaned identity key")


def process_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str | bool]]]:
    for index, row in enumerate(rows, start=1):
        row["row_id"] = str(index)
    identities: dict[str, list[dict[str, str]]] = defaultdict(list)
    sku_names: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        identities[identity_key(row)].append(row)
        sku = (row.get("parent_sku") or "").strip()
        if sku:
            sku_names[sku].add(normalise(row.get("parent_name", "")))

    cleaned: list[dict[str, str]] = []
    review: list[dict[str, str | bool]] = []
    for group_rows in identities.values():
        parent_name = group_rows[0]["parent_name"]
        sku = group_rows[0]["parent_sku"].strip()
        sku_collision = bool(sku and len(sku_names[sku]) > 1)
        url_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in group_rows:
            url_groups[_url_path(row["url"])].append(row)

        canonical = VERIFIED_CANONICALS.get(parent_name, "not_explicitly_verified")
        if canonical is None:
            for row in group_rows:
                title = PAGE_TITLES.get(_url_path(row["url"]), "")
                review.append(_review_row(row, sku_collision, False, "unresolved", "strict_exclusion", "egolite", title))
            continue

        if canonical != "not_explicitly_verified":
            selected_candidates = url_groups.get(canonical, [])
            if not selected_candidates:
                for row in group_rows:
                    title = PAGE_TITLES.get(_url_path(row["url"]), "")
                    review.append(_review_row(row, sku_collision, False, "unresolved", "missing_verified_url", "egolite", title))
                continue
            chosen = _best_row(selected_candidates, parent_name)
            cleaned.append(chosen)
            for row in group_rows:
                path = _url_path(row["url"])
                title = PAGE_TITLES.get(path, "")
                selected = row is chosen
                decision = "selected" if selected else "rejected"
                reason = "verified_pdp_title_match" if selected else "noncanonical_or_duplicate_candidate"
                review.append(_review_row(row, sku_collision, selected, decision, reason, "egolite", title))
            continue

        if len(url_groups) == 1 and not sku_collision:
            only_path, only_candidates = next(iter(url_groups.items()))
            title = PAGE_TITLES.get(only_path, "")
            assessment = assess_candidate(
                parent_name,
                only_candidates[0].get("name", ""),
                only_candidates[0].get("volume(ml)", ""),
                only_candidates[0].get("url", ""),
                title,
            ) if title else None
            if _is_listing_url(only_candidates[0].get("url", "")) or (assessment and assessment["action"] != "accept"):
                for row in group_rows:
                    review.append(
                        _review_row(
                            row,
                            sku_collision,
                            False,
                            "unresolved",
                            "listing_url" if _is_listing_url(only_candidates[0].get("url", "")) else assessment["reason"],
                            "egolite" if title else "url_rule",
                            title,
                        )
                    )
                continue
            chosen = _best_row(group_rows, parent_name)
            cleaned.append(chosen)
            method = "egolite_title" if title else "source_exact_url"
            selected_reason = "title_match" if title else "single_candidate"
            for row in group_rows:
                selected = row is chosen
                review.append(
                    _review_row(
                        row,
                        sku_collision,
                        selected,
                        "selected" if selected else "deduplicated",
                        selected_reason if selected else "same_url_duplicate",
                        method,
                        title,
                    )
                )
            continue

        assessments = {
            path: assess_candidate(
                parent_name,
                candidates[0].get("name", ""),
                candidates[0].get("volume(ml)", ""),
                candidates[0].get("url", ""),
                PAGE_TITLES.get(path, ""),
            )
            for path, candidates in url_groups.items()
        }
        accepted_paths = [path for path, result in assessments.items() if result["action"] == "accept"]
        if len(accepted_paths) == 1:
            chosen = _best_row(url_groups[accepted_paths[0]], parent_name)
            cleaned.append(chosen)
            for row in group_rows:
                path = _url_path(row["url"])
                result = assessments[path]
                selected = row is chosen
                review.append(
                    _review_row(
                        row,
                        sku_collision,
                        selected,
                        "selected" if selected else "rejected",
                        "title_match" if selected else result["reason"],
                        "egolite",
                        PAGE_TITLES.get(path, ""),
                    )
                )
        else:
            for row in group_rows:
                path = _url_path(row["url"])
                result = assessments[path]
                review.append(
                    _review_row(
                        row,
                        sku_collision,
                        False,
                        "unresolved",
                        result["reason"] if result["action"] != "accept" else "multiple_accepted_candidates",
                        "egolite",
                        PAGE_TITLES.get(path, ""),
                    )
                )
    validate_outputs(cleaned, review, rows)
    return cleaned, review


def write_outputs(cleaned: list[dict[str, str]], review: list[dict[str, str | bool]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_path = output_dir / "humblewine_unclefossil_cleaned.csv"
    review_path = output_dir / "humblewine_unclefossil_review.csv"
    with clean_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cleaned)
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in review:
            serialized = {key: str(value).lower() if isinstance(value, bool) else value for key, value in row.items()}
            writer.writerow(serialized)


def load_page_titles(path: Path | None) -> None:
    if path is None:
        return
    with path.open(encoding="utf-8") as handle:
        snapshots = json.load(handle)
    if not isinstance(snapshots, dict):
        raise ValueError("page-title snapshot must be a JSON object")
    for url, title in snapshots.items():
        if isinstance(url, str) and isinstance(title, str):
            PAGE_TITLES[_url_path(url)] = title


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("/Users/wyl/Downloads/humblewine-unclefossil.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/unclefossil_deduplication"))
    parser.add_argument("--page-titles", type=Path, help="JSON snapshot of URL-to-page-title verification evidence")
    args = parser.parse_args()
    load_page_titles(args.page_titles)
    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SOURCE_FIELDS:
            raise ValueError(f"unexpected source columns: {reader.fieldnames}")
        rows = list(reader)
    cleaned, review = process_rows(rows)
    write_outputs(cleaned, review, args.output_dir)
    selected = sum(row["selected"] is True for row in review)
    unresolved = sum(row["decision"] == "unresolved" for row in review)
    print(f"input_rows={len(rows)} cleaned_rows={len(cleaned)} selected_rows={selected} unresolved_rows={unresolved}")


if __name__ == "__main__":
    main()

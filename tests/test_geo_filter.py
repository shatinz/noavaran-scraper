import pytest
from geo_filter import (
    classify_geography,
    is_large_scale_project,
    is_top_tier_student,
    should_admit_entity,
    should_admit_project,
)


def test_classify_geography():
    assert classify_geography("دفتر معماری در خیابان مرداویج اصفهان") == "isfahan"
    assert classify_geography("شرکت ساختمانی شاهین شهر") == "isfahan"
    assert classify_geography("پروژه برج میلاد تهران") == "other_iran"
    assert classify_geography("طراحی نما در شیراز") == "other_iran"
    assert classify_geography("Facade engineering consultancy in Dubai UAE") == "international"


def test_is_large_scale_project():
    assert is_large_scale_project("احداث برج مسکونی ۳۰ طبقه با نمای شیشه‌ای کرتین وال") is True
    assert is_large_scale_project("پروژه بیمارستان فوق تخصصی ۵۰۰۰ متر مربع") is True
    assert is_large_scale_project("مجتمع تجاری و مگامال") is True
    assert is_large_scale_project("بازسازی مغازه ۲۰ متری پوشاک") is False
    assert is_large_scale_project("ویلای دوبلکس ۳۰۰ متری در چالوس") is False


def test_is_top_tier_student():
    # Tehran university student with award
    res, reason = is_top_tier_student("دانشجوی کارشناسی ارشد دانشگاه تهران و برنده جایزه معمار")
    assert res is True
    assert "دانشگاه تهران" in reason or "جایزه معمار" in reason

    # Shahid Beheshti student
    res, reason = is_top_tier_student("دانشجوی معماری دانشگاه شهید بهشتی")
    assert res is True

    # Generic student without top university or awards
    res, reason = is_top_tier_student("دانشجوی معماری دانشگاه آزاد چالوس")
    assert res is False


def test_should_admit_entity():
    # Isfahan student admitted unconditionally
    admit, _ = should_admit_entity("student", "isfahan", "دانشجوی ترم ۱ دانشگاه آزاد نجف آباد")
    assert admit is True

    # Non-Isfahan generic student rejected
    admit, _ = should_admit_entity("student", "other_iran", "دانشجوی ترم ۱ دانشگاه پیام نور رشت")
    assert admit is False

    # Non-Isfahan top student admitted
    admit, _ = should_admit_entity("student", "other_iran", "دانشجوی دانشگاه علم و صنعت و رتبه اول مسابقه معماری")
    assert admit is True

    # All offices admitted
    admit, _ = should_admit_entity("office", "other_iran", "دفتر معماری در مشهد")
    assert admit is True


def test_should_admit_project():
    # Isfahan project admitted regardless of size
    admit, _ = should_admit_project("isfahan", "ویلای تک واحده در دهکده زیتون اصفهان")
    assert admit is True

    # Non-Isfahan small project rejected
    admit, _ = should_admit_project("other_iran", "بازسازی واحد مسکونی در کرج")
    assert admit is False

    # Non-Isfahan large project admitted
    admit, _ = should_admit_project("other_iran", "برج تجاری اداری ۲۰ طبقه در تهران با نمای لامل")
    assert admit is True

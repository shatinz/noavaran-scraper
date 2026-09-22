import os
import tempfile
import tkinter as tk
import pytest

from ui import ScraperApp
from models import ContactEntity, ActiveProject
from database import init_db, upsert_contact_db, upsert_project_db, save_ambiguous_review


@pytest.fixture
def temp_ui_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)

    # Populate test entities
    c1 = ContactEntity(
        entity_type="office",
        name="دفتر معماری پادیاو",
        role="مدیر طراحی",
        company="استودیو معماری پادیاو",
        city="Isfahan",
        phone="09131112233",
        email="padiav@example.com",
        social_handle="@padiav_arch",
        source_url="https://padiav.example.com",
        confidence="verified",
    )
    c2 = ContactEntity(
        entity_type="contractor",
        name="مهندس علیرضا رضایی",
        role="مجری نما و پنجره ترمال بریک",
        company="شرکت آروین نما",
        city="Tehran",
        phone="09123334455",
        email="rezaei@arvin.ir",
        social_handle="@arvin_facade",
        source_url="https://arvin.ir",
        confidence="high",
    )
    upsert_contact_db(c1, db_path)
    upsert_contact_db(c2, db_path)

    # Populate test project
    p1 = ActiveProject(
        project_name="برج تجاری اداری مهستان",
        city="Isfahan",
        scale_scope="18 طبقه تجاری اداری، نمای کرتین وال و ترمال بریک",
        associated_contractors="آروین نما; پرشیا پنجره",
        associated_architects="مهندسین مشاور نقش جهان",
        contact_info="03131313160",
        source_url="https://example.com/mahestan",
        confidence="high",
    )
    upsert_project_db(p1, db_path)

    save_ambiguous_review("contact", c1.id, c2.model_dump(), 78.5, "fuzzy composite match 78.5%", db_path)

    yield db_path

    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


def test_ui_initialization_and_tabs(temp_ui_db):
    root = tk.Tk()
    root.withdraw()  # Hidden for headless tests
    try:
        app = ScraperApp(root, db_path=temp_ui_db)
        app._initial_load()
        root.update()

        # Check tab tabs exist
        tab_names = [app.notebook.tab(i, "text") for i in range(app.notebook.index("end"))]
        assert len(tab_names) == 5
        assert any("Crawl" in t or "پویشگر" in t for t in tab_names)
        assert any("Contacts" in t or "مخاطبین" in t for t in tab_names)
        assert any("Active Projects" in t or "پروژه‌ها" in t for t in tab_names)
        assert any("Ambiguous Reviews" in t or "برخوردهای مبهم" in t for t in tab_names)
        assert any("Export" in t or "خروجی‌ها" in t for t in tab_names)

        # Check stats loaded
        assert app.lbl_stat_contacts.cget("text") == "2"
        assert app.lbl_stat_projects.cget("text") == "1"
        assert app.lbl_stat_reviews.cget("text") == "1"

        # Check table items populated
        assert len(app.tree_contacts.get_children()) == 2
        assert len(app.tree_projects.get_children()) == 1
        assert len(app.tree_reviews.get_children()) == 1

    finally:
        root.destroy()


def test_ui_filtering_contacts(temp_ui_db):
    root = tk.Tk()
    root.withdraw()
    try:
        app = ScraperApp(root, db_path=temp_ui_db)
        app._initial_load()
        root.update()

        # Filter by text search 'پادیاو'
        app.ent_search_contacts.insert(0, "پادیاو")
        app._filter_contacts()
        assert len(app.tree_contacts.get_children()) == 1

        # Clear search
        app.ent_search_contacts.delete(0, tk.END)
        app._filter_contacts()
        assert len(app.tree_contacts.get_children()) == 2

        # Filter by type 'contractor'
        app.cmb_filter_type.set("contractor")
        app._filter_contacts()
        assert len(app.tree_contacts.get_children()) == 1

        # Filter by city 'Isfahan'
        app.cmb_filter_type.set("همه (All)")
        app.cmb_filter_city.set("Isfahan")
        app._filter_contacts()
        assert len(app.tree_contacts.get_children()) == 1

    finally:
        root.destroy()


def test_ui_filtering_projects(temp_ui_db):
    root = tk.Tk()
    root.withdraw()
    try:
        app = ScraperApp(root, db_path=temp_ui_db)
        app._initial_load()
        root.update()

        # Search for 'مهستان'
        app.ent_search_projects.insert(0, "مهستان")
        app._filter_projects()
        assert len(app.tree_projects.get_children()) == 1

        # Search for non-existent
        app.ent_search_projects.delete(0, tk.END)
        app.ent_search_projects.insert(0, "پروژه ناموجود ۱۲۳")
        app._filter_projects()
        assert len(app.tree_projects.get_children()) == 0

    finally:
        root.destroy()


def test_ui_sorting(temp_ui_db):
    root = tk.Tk()
    root.withdraw()
    try:
        app = ScraperApp(root, db_path=temp_ui_db)
        app._initial_load()
        root.update()

        # Sort contacts by name
        app._sort_tree(app.tree_contacts, app.contacts_sort_state, "name")
        children = app.tree_contacts.get_children()
        assert len(children) == 2

        # Sort projects by name
        app._sort_tree(app.tree_projects, app.projects_sort_state, "name")
        p_children = app.tree_projects.get_children()
        assert len(p_children) == 1

    finally:
        root.destroy()

import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))

from config import regole_fornitore
from tests.sintetico import crea_listino_sintetico

CAMPIONE_REALE = RADICE / "samples" / "Listino_JBL_Gen_2026.pdf"


@pytest.fixture
def regole():
    return regole_fornitore("jbl_exhibo")


@pytest.fixture
def pdf_sintetico(tmp_path):
    return crea_listino_sintetico(tmp_path / "sintetico.pdf")

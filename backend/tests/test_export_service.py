from app.services import export_service


def test_build_export_filename_transliterates_umlauts():
    assert export_service.build_export_filename("Müller", "Jörg") == "Mueller_Joerg_export.pdf"


def test_build_export_filename_transliterates_eszett():
    assert export_service.build_export_filename("Straß", "Anna") == "Strass_Anna_export.pdf"


def test_build_export_filename_strips_other_diacritics_to_base_letter():
    assert export_service.build_export_filename("Renée", "José") == "Renee_Jose_export.pdf"


def test_build_export_filename_replaces_remaining_special_characters_with_dash():
    assert export_service.build_export_filename("O'Brien", "Anne-Marie") == "O-Brien_Anne-Marie_export.pdf"


def test_build_export_filename_replaces_spaces_with_dash():
    assert export_service.build_export_filename("von Bergmann", "Karl Heinz") == "von-Bergmann_Karl-Heinz_export.pdf"

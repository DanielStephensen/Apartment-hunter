"""Parser tests built from text the real sites actually produce."""

from __future__ import annotations

import unittest

from apartment_hunter.parsing import (
    normalize_units,
    parse_area,
    parse_delevenlig,
    parse_postal_code,
    parse_price,
    parse_rooms,
    prettify_slug,
)

# Verbatim card text captured from the live sites.
ELTOFT = "MØBLERET Andre typer Sølvgade 20, 2. tv, København K Leje pr. md. 55.500 DKK Boligareal 160 m 2 Værelser 5 Se bolig"
KEREBY = "Delevenlig Roskildevej 47, st., 2000 Frederiksberg 6-værelses lejlighed 34.667 kr. pr. md."
HEIMSTADEN = "Amagerbrogade 148, 2. tv. 2300 København S 5 vær. 118 m² 17.208 kr."


class TestPrice(unittest.TestCase):
    def test_reads_rent_from_real_cards(self):
        self.assertEqual(parse_price(ELTOFT), 55_500)
        self.assertEqual(parse_price(KEREBY), 34_667)
        self.assertEqual(parse_price(HEIMSTADEN), 17_208)

    def test_ignores_deposit_and_utilities(self):
        self.assertEqual(parse_price("Husleje 12.500 kr. Depositum 37.500 kr."), 12_500)
        self.assertIsNone(parse_price("Depositum 37.500 kr."))
        self.assertIsNone(parse_price("Aconto varme 850 kr."))

    def test_prefers_the_amount_marked_as_rent(self):
        self.assertEqual(parse_price("Indskud 20.000 kr. Månedlig leje 18.400 kr."), 18_400)

    def test_a_truncated_context_window_does_not_swallow_the_rent(self):
        # The window around the amount can cut mid-word ("Værel…"); a loosely
        # anchored 'el' rule used to read that as an electricity charge.
        self.assertEqual(parse_price("Leje pr. md. 55.500 DKK Boligareal 160 m² Værelser 5"), 55_500)

    def test_requires_a_currency_anchor(self):
        self.assertIsNone(parse_price("130 m² 2300 København S"))

    def test_rejects_implausible_amounts(self):
        self.assertIsNone(parse_price("5 kr."))
        self.assertIsNone(parse_price("2.500.000 kr."))


class TestRooms(unittest.TestCase):
    def test_reads_rooms_from_real_cards(self):
        self.assertEqual(parse_rooms(ELTOFT), 5)
        self.assertEqual(parse_rooms(KEREBY), 6)
        self.assertEqual(parse_rooms(HEIMSTADEN), 5)

    def test_flattened_superscript_is_not_read_as_rooms(self):
        # "m<sup>2</sup>" flattens to "m 2"; that 2 sat right before "Værelser".
        self.assertEqual(parse_rooms("Boligareal 160 m 2 Værelser 5"), 5)

    def test_wordings(self):
        self.assertEqual(parse_rooms("5 værelser"), 5)
        self.assertEqual(parse_rooms("Antal værelser: 7"), 7)
        self.assertEqual(parse_rooms("4-værelses lejlighed"), 4)
        self.assertEqual(parse_rooms("3 rum"), 3)
        self.assertIsNone(parse_rooms("Ingen oplysninger"))

    def test_floor_number_is_not_a_room_count(self):
        self.assertIsNone(parse_rooms("Sølvgade 20, 2. tv, København K"))


class TestArea(unittest.TestCase):
    def test_reads_area(self):
        self.assertEqual(parse_area(ELTOFT), 160)
        self.assertEqual(parse_area(HEIMSTADEN), 118)
        self.assertEqual(parse_area("Størrelse: 95"), 95)
        self.assertEqual(parse_area("130 kvm"), 130)

    def test_normalize_units(self):
        self.assertEqual(normalize_units("160 m 2"), "160 m²")
        self.assertEqual(normalize_units("160 m2"), "160 m²")


class TestPostalCode(unittest.TestCase):
    def test_prefers_the_code_followed_by_a_city(self):
        self.assertEqual(parse_postal_code("Sølvgade 20, 2. tv, 1307 København K"), "1307")
        self.assertEqual(parse_postal_code(KEREBY), "2000")

    def test_house_number_is_not_a_postal_code(self):
        self.assertEqual(parse_postal_code("Amagerbrogade 148, 2. tv. 2300 København S"), "2300")

    def test_no_code(self):
        self.assertIsNone(parse_postal_code("Ukendt adresse"))

    def test_a_bare_number_is_not_guessed_at(self):
        # Guessing here is worse than not knowing: a wrong code drops a
        # Copenhagen apartment as being out of town.
        self.assertIsNone(parse_postal_code("Sag 1234 oprettet"))

    def test_a_year_is_not_a_postal_code(self):
        self.assertIsNone(parse_postal_code("Ledig fra 2026"))
        self.assertIsNone(parse_postal_code("Opført 1899, renoveret 2026"))
        self.assertIsNone(parse_postal_code("© 2026 Juli Living"))

    def test_a_known_code_still_wins_without_a_city(self):
        self.assertEqual(parse_postal_code("Postnr 2100", {"2100"}), "2100")


class TestDelevenlig(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(parse_delevenlig(KEREBY), "ja")
        self.assertEqual(parse_delevenlig("Boligen er delevenlig"), "ja")
        self.assertEqual(parse_delevenlig("Dele-venlig lejlighed"), "ja")
        self.assertEqual(parse_delevenlig("Egnet til deling"), "ja")

    def test_negative_wins_over_the_word_itself(self):
        self.assertEqual(parse_delevenlig("Lejligheden er ikke delevenlig"), "nej")
        self.assertEqual(parse_delevenlig("Delevenlig: nej"), "nej")
        self.assertEqual(parse_delevenlig("Boligen er ikke egnet til deling"), "nej")

    def test_silence_is_unknown(self):
        # Most sites never mention it — that must not read as a "no".
        self.assertEqual(parse_delevenlig(HEIMSTADEN), "ukendt")


class TestSlug(unittest.TestCase):
    def test_prettify(self):
        self.assertEqual(
            prettify_slug("/bolig/strandboulevarden-61-5-th-2100-kobenhavn/"),
            "Strandboulevarden 61 5 Th 2100 Kobenhavn",
        )


if __name__ == "__main__":
    unittest.main()

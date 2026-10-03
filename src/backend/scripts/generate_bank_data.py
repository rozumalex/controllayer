# The data tables are laid out by hand, wider than the code.
# ruff: noqa: E501
"""Generate the Golden Socks bank data in scripts/bank_data.

Every person, company and number is made up, but the tables hang together the
way a bank's would:

- A client's AUM is the sum of its open accounts, and its credit limit covers
  their credit exposure.
- Trades book on the client's own trading accounts, at the instrument's price
  on that day, by a trader on the desk and in the office for that market.
- Payments go to other clients' accounts or to external ones with valid IBANs,
  and AML and fraud scores, alerts and statuses follow from them.
- Research targets follow the same prices the trades use, and each report is
  written by an analyst in Global Investment Research.
- Relationship managers, traders, analysts and compliance officers are
  employees in the right division, with a manager above them.

The seed is fixed, so every run writes the same files. The data catalog and
the identity profiles are kept by hand. Run from src/backend:
`uv run python -m scripts.generate_bank_data`, then `./dev seed`.
"""

import csv
import gzip
import io
import math
import random
import string
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from scripts.seed import DATA_DIR

rng = random.Random(2026)
TODAY = date(2026, 10, 3)


def pattern(spec: str) -> str:
    """# is a digit, % a digit from 1 to 9, ? an uppercase letter."""
    pick = {"#": string.digits, "%": "123456789", "?": string.ascii_uppercase}
    return "".join(rng.choice(pick[c]) if c in pick else c for c in spec)


def weighted[T](options: Mapping[T, float]) -> T:
    return rng.choices(list(options), weights=list(options.values()))[0]


def business_days(start: date, end: date) -> list[date]:
    days = (start + timedelta(n) for n in range((end - start).days + 1))
    return [d for d in days if d.weekday() < 5]


def add_business_days(day: date, n: int) -> date:
    while n:
        day += timedelta(1)
        n -= day.weekday() < 5
    return day


def slug(text: str) -> str:
    text = text.replace("ł", "l").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c for c in text.lower() if c.isalnum())


LAST_DAY = business_days(TODAY - timedelta(5), TODAY - timedelta(1))[-1]

# fmt: off
# Names: male first names, female first names, last names, and female last
# names where the language has them.
NAMES: dict[str, tuple[tuple[str, ...], ...]] = {
    "en": (
        ("James", "Michael", "David", "Daniel", "Matthew", "Ryan", "Andrew", "Thomas",
         "Benjamin", "Christopher", "Patrick", "Jonathan", "Samuel", "Nathan", "William",
         "Edward", "Henry", "Oliver", "George", "Robert"),
        ("Olivia", "Emma", "Sophia", "Charlotte", "Amelia", "Grace", "Hannah", "Lauren",
         "Megan", "Natalie", "Rachel", "Claire", "Emily", "Katherine", "Abigail",
         "Victoria", "Eleanor", "Lucy", "Sarah", "Alice"),
        ("Whitaker", "Caldwell", "Brennan", "Hollis", "Prescott", "Langley", "Sutton",
         "Mercer", "Kendall", "Fletcher", "Dalton", "Ashford", "Winslow", "Thornton",
         "Beckett", "Garrison", "Holloway", "Pierce", "Radcliffe", "Sinclair", "Townsend",
         "Calloway", "Donovan", "Ellison", "Fairbanks", "Gallagher", "Harrington",
         "Kingsley", "Lockhart", "Maddox", "Norwood", "Pembroke", "Quinlan", "Stratton",
         "Underwood", "Whitmore", "Barlow", "Chandler", "Hughes", "Reid"),
    ),
    "de": (
        ("Lukas", "Felix", "Jonas", "Maximilian", "Paul", "Tobias", "Florian", "Matthias",
         "Stefan", "Niklas", "Andreas", "Christian"),
        ("Anna", "Lea", "Lena", "Sophie", "Marie", "Laura", "Julia", "Katharina",
         "Johanna", "Clara", "Sabine", "Nina"),
        ("Brandt", "Vogel", "Kessler", "Hartmann", "Lindner", "Albrecht", "Weiss",
         "Krüger", "Baumann", "Seidel", "Kaiser", "Lorenz", "Engel", "Brunner", "Huber",
         "Frey", "Steiner", "Gerber", "Keller", "Moser"),
    ),
    "fr": (
        ("Louis", "Hugo", "Arthur", "Jules", "Antoine", "Mathieu", "Nicolas", "Julien",
         "Théo", "Romain"),
        ("Camille", "Chloé", "Manon", "Léa", "Inès", "Juliette", "Margaux", "Élise",
         "Pauline", "Claire"),
        ("Lefèvre", "Moreau", "Girard", "Fontaine", "Rousseau", "Mercier", "Blanchard",
         "Garnier", "Chevalier", "Faure", "Lambert", "Bonnet", "Marchand", "Renaud",
         "Leclerc", "Perrin", "Gauthier", "Vidal"),
    ),
    "nl": (
        ("Daan", "Bram", "Thijs", "Ruben", "Joris", "Sem"),
        ("Sanne", "Lotte", "Femke", "Eva", "Anouk", "Fleur"),
        ("de Vries", "van Dijk", "Bakker", "Visser", "Smit", "Meijer", "de Boer",
         "Mulder", "Bos", "Vos", "van Leeuwen", "Dekker"),
    ),
    "it": (
        ("Marco", "Luca", "Alessandro", "Matteo", "Andrea", "Davide", "Lorenzo"),
        ("Giulia", "Francesca", "Chiara", "Sara", "Elena", "Martina", "Alessia"),
        ("Rossi", "Ferrari", "Esposito", "Bianchi", "Romano", "Colombo", "Ricci",
         "Marino", "Greco", "Bruno", "Gallo", "Conti", "De Luca", "Mancini", "Costa"),
    ),
    "es": (
        ("Javier", "Pablo", "Alejandro", "Diego", "Sergio", "Andrés", "Carlos", "Miguel"),
        ("Lucía", "María", "Carmen", "Sofía", "Elena", "Valeria", "Paula", "Isabel"),
        ("García", "Fernández", "López", "Martínez", "Sánchez", "Romero", "Navarro",
         "Torres", "Domínguez", "Vázquez", "Ramos", "Serrano", "Molina", "Morales",
         "Ortega"),
    ),
    "pl": (
        ("Jakub", "Kacper", "Mateusz", "Piotr", "Tomasz", "Michał", "Krzysztof", "Paweł"),
        ("Zuzanna", "Julia", "Maja", "Katarzyna", "Agnieszka", "Magdalena", "Aleksandra",
         "Monika"),
        ("Nowak", "Wójcik", "Kowalczyk", "Woźniak", "Mazur", "Krawczyk", "Kaczmarek",
         "Zając", "Król", "Wieczorek", "Wróbel", "Dudek", "Pawlak", "Walczak", "Sikora"),
    ),
    "cz": (
        ("Jan", "Tomáš", "Petr", "Martin", "Ondřej", "Jakub", "Lukáš"),
        ("Tereza", "Eliška", "Kateřina", "Lucie", "Veronika", "Barbora", "Petra"),
        ("Novák", "Svoboda", "Dvořák", "Černý", "Procházka", "Kučera", "Veselý", "Horák"),
        ("Nováková", "Svobodová", "Dvořáková", "Černá", "Procházková", "Kučerová",
         "Veselá", "Horáková"),
    ),
    "jp": (
        ("Haruto", "Sota", "Ren", "Takumi", "Kenji", "Daiki", "Hiroshi", "Yuto"),
        ("Yui", "Hina", "Aoi", "Sakura", "Yuki", "Mei", "Aiko", "Naomi"),
        ("Sato", "Suzuki", "Takahashi", "Tanaka", "Watanabe", "Ito", "Yamamoto",
         "Nakamura", "Kobayashi", "Kato", "Yoshida", "Yamada", "Matsumoto", "Inoue"),
    ),
    "zh": (
        ("Wei", "Jun", "Hao", "Ming", "Kelvin", "Eric", "Jason", "Raymond"),
        ("Mei Ling", "Xin Yi", "Jia Hui", "Vivian", "Karen", "Michelle", "Shu Fen"),
        ("Chan", "Wong", "Lee", "Cheung", "Lau", "Ng", "Tan", "Lim", "Goh", "Ong", "Teo",
         "Leung", "Ho", "Yeung"),
    ),
    "in": (
        ("Arjun", "Rohan", "Vikram", "Aditya", "Rahul", "Karan", "Siddharth"),
        ("Priya", "Ananya", "Kavya", "Isha", "Neha", "Meera", "Divya"),
        ("Sharma", "Iyer", "Mehta", "Reddy", "Nair", "Kapoor", "Banerjee", "Desai",
         "Rao", "Menon", "Joshi", "Chatterjee"),
    ),
    "br": (
        ("João", "Pedro", "Lucas", "Gabriel", "Rafael", "Thiago", "Bruno"),
        ("Ana", "Beatriz", "Mariana", "Larissa", "Camila", "Fernanda", "Juliana"),
        ("Silva", "Santos", "Oliveira", "Souza", "Pereira", "Costa", "Almeida",
         "Ribeiro", "Carvalho", "Gomes", "Rocha", "Barbosa"),
    ),
    "ae": (
        ("Omar", "Khalid", "Ahmed", "Saeed", "Rashid", "Hamdan", "Yousef"),
        ("Fatima", "Mariam", "Noura", "Aisha", "Layla", "Sara", "Hessa"),
        ("Al Mansoori", "Al Suwaidi", "Al Mazrouei", "Al Hashimi", "Al Falasi",
         "Al Ketbi", "Al Dhaheri", "Al Shamsi", "Al Marzooqi", "Al Zaabi"),
    ),
}

# fmt: on


@dataclass(frozen=True)
class Country:
    name: str
    currency: str
    names: str
    phone: str
    # (city, postcode pattern), the main financial centre first.
    cities: tuple[tuple[str, str], ...]
    streets: tuple[str, ...]
    address: str
    tax_id: str
    legal: tuple[str, ...]
    region: str
    tld: str
    # Higher for jurisdictions under enhanced AML monitoring.
    risk: int = 0
    weight: float = 1


# fmt: off
COUNTRIES = {
    "US": Country("United States", "USD", "en", "+1 %## %## ####",
                  (("New York", "100##"), ("Chicago", "606##"), ("Boston", "021##"),
                   ("San Francisco", "941##"), ("Greenwich", "068##"), ("Miami", "331##"),
                   ("Dallas", "752##"), ("Salt Lake City", "841##")),
                  ("Park Avenue", "Madison Avenue", "Lexington Avenue", "Hudson Street",
                   "Greenwich Street", "Broad Street", "Water Street", "Market Street",
                   "State Street", "Maple Avenue", "Oak Street", "Washington Street"),
                  "{n} {street}, {city} {postcode}", "##-#######",
                  ("Inc.", "LLC", "Corp."), "Americas", ".com", weight=30),
    "GB": Country("United Kingdom", "GBP", "en", "+44 20 #### ####",
                  (("London", "EC#? #??"), ("Edinburgh", "EH# #??"),
                   ("Manchester", "M# #??")),
                  ("Moorgate", "Cheapside", "Bishopsgate", "Fenchurch Street",
                   "Cannon Street", "Gresham Street", "Threadneedle Street",
                   "Victoria Street", "Kensington Park Road", "Holland Park Avenue"),
                  "{n} {street}, {city} {postcode}", "##########",
                  ("Ltd", "plc", "LLP"), "Europe", ".co.uk", weight=12),
    "DE": Country("Germany", "EUR", "de", "+49 69 #### ####",
                  (("Frankfurt", "603##"), ("Munich", "803##"), ("Hamburg", "203##")),
                  ("Taunusanlage", "Mainzer Landstraße", "Neue Mainzer Straße",
                   "Bockenheimer Landstraße", "Kaiserstraße", "Goethestraße",
                   "Schillerstraße", "Lindenstraße", "Gartenstraße"),
                  "{street} {n}, {postcode} {city}", "DE#########",
                  ("GmbH", "AG", "SE"), "Europe", ".de", weight=6),
    "FR": Country("France", "EUR", "fr", "+33 1 ## ## ## ##",
                  (("Paris", "750##"), ("Lyon", "6900#")),
                  ("Rue de Rivoli", "Avenue de l'Opéra", "Boulevard Haussmann",
                   "Rue du Faubourg Saint-Honoré", "Avenue Montaigne", "Rue de la Paix",
                   "Rue La Fayette", "Avenue Kléber"),
                  "{n} {street}, {postcode} {city}", "### ### ###",
                  ("SA", "SAS"), "Europe", ".fr", weight=5),
    "NL": Country("Netherlands", "EUR", "nl", "+31 20 ### ####",
                  (("Amsterdam", "10## ??"), ("Rotterdam", "30## ??")),
                  ("Herengracht", "Keizersgracht", "Prinsengracht", "Gustav Mahlerlaan",
                   "Coolsingel", "Weena"),
                  "{street} {n}, {postcode} {city}", "NL#########B01",
                  ("B.V.", "N.V."), "Europe", ".nl", weight=3),
    "IT": Country("Italy", "EUR", "it", "+39 02 #### ####",
                  (("Milan", "201##"), ("Rome", "001##")),
                  ("Via Monte Napoleone", "Corso Venezia", "Via Dante", "Piazza Cordusio",
                   "Via del Corso", "Via Veneto"),
                  "{street} {n}, {postcode} {city}", "IT###########",
                  ("S.p.A.", "S.r.l."), "Europe", ".it", weight=3),
    "ES": Country("Spain", "EUR", "es", "+34 91 ### ## ##",
                  (("Madrid", "280##"), ("Barcelona", "080##")),
                  ("Paseo de la Castellana", "Calle de Serrano", "Gran Vía",
                   "Calle de Alcalá", "Passeig de Gràcia", "Avinguda Diagonal"),
                  "{street} {n}, {postcode} {city}", "B########",
                  ("S.A.", "S.L."), "Europe", ".es", weight=3),
    "IE": Country("Ireland", "EUR", "en", "+353 1 ### ####",
                  (("Dublin", "D0% ?#??"),),
                  ("Sir John Rogerson's Quay", "Harcourt Street", "St Stephen's Green",
                   "Merrion Square", "Baggot Street"),
                  "{n} {street}, {city} {postcode}", "IE#######?",
                  ("Limited", "DAC", "plc"), "Europe", ".ie", weight=2),
    "CH": Country("Switzerland", "CHF", "de", "+41 44 ### ## ##",
                  (("Zurich", "80##"), ("Geneva", "12##")),
                  ("Bahnhofstrasse", "Paradeplatz", "Talstrasse", "Seefeldstrasse",
                   "Rue du Rhône", "Quai du Mont-Blanc"),
                  "{street} {n}, {postcode} {city}", "CHE-###.###.###",
                  ("AG", "SA", "GmbH"), "Europe", ".ch", weight=6),
    "PL": Country("Poland", "PLN", "pl", "+48 22 ### ## ##",
                  (("Warsaw", "00-###"), ("Krakow", "31-###")),
                  ("ul. Marszałkowska", "ul. Prosta", "al. Jerozolimskie", "ul. Złota",
                   "ul. Grzybowska", "ul. Floriańska"),
                  "{street} {n}, {postcode} {city}", "###-###-##-##",
                  ("Sp. z o.o.", "S.A."), "Europe", ".pl", weight=2),
    "CZ": Country("Czechia", "CZK", "cz", "+420 2## ### ###",
                  (("Prague", "1%# ##"), ("Brno", "6%# ##")),
                  ("Václavské náměstí", "Na Příkopě", "Národní", "Pařížská",
                   "Vinohradská", "Masarykova"),
                  "{street} {n}, {postcode} {city}", "CZ########",
                  ("s.r.o.", "a.s."), "Europe", ".cz", weight=1.5),
    "JP": Country("Japan", "JPY", "jp", "+81 3 #### ####",
                  (("Tokyo", "1##-####"), ("Osaka", "5##-####")),
                  ("Marunouchi, Chiyoda-ku", "Otemachi, Chiyoda-ku",
                   "Nihonbashi, Chuo-ku", "Roppongi, Minato-ku", "Akasaka, Minato-ku"),
                  "{n} {street}, {city} {postcode}", "%############",
                  ("K.K.", "Co., Ltd."), "Asia", ".co.jp", weight=6),
    "HK": Country("Hong Kong", "HKD", "zh", "+852 %### ####", (("Hong Kong", ""),),
                  ("Queen's Road Central", "Des Voeux Road Central",
                   "Connaught Road Central", "Harcourt Road", "Nathan Road"),
                  "{n} {street}, {city}", "########",
                  ("Limited",), "Asia", ".com.hk", risk=1, weight=4),
    "SG": Country("Singapore", "SGD", "zh", "+65 6### ####",
                  (("Singapore", "0#####"),),
                  ("Raffles Place", "Marina Boulevard", "Shenton Way", "Collyer Quay",
                   "Orchard Road", "Cecil Street"),
                  "{n} {street}, {city} {postcode}", "20#######?",
                  ("Pte. Ltd.",), "Asia", ".com.sg", weight=4),
    "AU": Country("Australia", "AUD", "en", "+61 2 #### ####",
                  (("Sydney", "2000"), ("Melbourne", "3000")),
                  ("George Street", "Pitt Street", "Macquarie Street", "Collins Street",
                   "Bourke Street", "Martin Place"),
                  "{n} {street}, {city} {postcode}", "%# ### ### ###",
                  ("Pty Ltd",), "Asia", ".com.au", weight=3),
    "CA": Country("Canada", "CAD", "en", "+1 416 ### ####",
                  (("Toronto", "M5? #?#"), ("Montreal", "H3? #?#")),
                  ("Bay Street", "King Street West", "Front Street West", "Yonge Street",
                   "Rue Sherbrooke Ouest", "Boulevard René-Lévesque"),
                  "{n} {street}, {city} {postcode}", "#########RC0001",
                  ("Inc.", "Ltd."), "Americas", ".ca", weight=3),
    "IN": Country("India", "INR", "in", "+91 22 #### ####",
                  (("Mumbai", "4000##"), ("Bengaluru", "5600##")),
                  ("Nariman Point", "Bandra Kurla Complex", "Dalal Street", "Marine Drive",
                   "MG Road", "Residency Road"),
                  "{n} {street}, {city} {postcode}", "?????####?",
                  ("Private Limited", "Limited"), "Asia", ".in", risk=1, weight=2),
    "BR": Country("Brazil", "BRL", "br", "+55 11 ####-####",
                  (("Sao Paulo", "01###-###"), ("Rio de Janeiro", "20###-###")),
                  ("Avenida Paulista", "Avenida Brigadeiro Faria Lima", "Rua Oscar Freire",
                   "Avenida Rio Branco"),
                  "{street} {n}, {postcode} {city}", "##.###.###/0001-##",
                  ("S.A.", "Ltda."), "Americas", ".com.br", risk=2, weight=2),
    "MX": Country("Mexico", "MXN", "es", "+52 55 #### ####",
                  (("Mexico City", "06###"), ("Monterrey", "64###")),
                  ("Paseo de la Reforma", "Avenida Presidente Masaryk",
                   "Avenida Insurgentes Sur", "Avenida Constitución"),
                  "{street} {n}, {postcode} {city}", "???######???",
                  ("S.A. de C.V.", "S. de R.L. de C.V."), "Americas", ".com.mx",
                  risk=2, weight=1.5),
    "AE": Country("UAE", "AED", "ae", "+971 4 ### ####",
                  (("Dubai", ""), ("Abu Dhabi", "")),
                  ("Sheikh Zayed Road", "DIFC Gate Avenue", "Al Maryah Island",
                   "Jumeirah Beach Road", "Al Wasl Road"),
                  "Office {n}, {street}, {city}", "100#########003",
                  ("LLC", "FZE", "Ltd"), "Europe", ".ae", risk=2, weight=2.5),
}
# fmt: on
# Destinations for payments only: no clients or offices there.
OFFSHORE = {"KY": "Ltd", "VG": "Limited", "PA": "S.A.", "CY": "Ltd", "MT": "Limited"}

# The length of the IBAN, and the pattern of the bank code at its start.
IBAN = {
    "GB": (22, "????"),
    "NL": (18, "????"),
    "IE": (22, "????"),
    "MT": (31, "????"),
    "IT": (27, "?"),
    "DE": (22, "########"),
    "FR": (27, "#####"),
    "ES": (24, "####"),
    "CH": (21, "#####"),
    "PL": (28, "########"),
    "CZ": (24, "####"),
    "AE": (23, "###"),
    "BR": (29, "########"),
    "CY": (28, "###"),
}


def aba() -> str:
    """A US routing number, with its check digit."""
    d = [0, rng.randint(1, 9), *(rng.randrange(10) for _ in range(6))]
    total = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + d[2] + d[5]
    return "".join(map(str, d)) + str(-total % 10)


def clabe(bank: str) -> str:
    """A Mexican CLABE, with its check digit."""
    digits = bank + pattern("### ###########").replace(" ", "")
    total = sum(int(c) * (3, 7, 1)[i % 3] % 10 for i, c in enumerate(digits))
    return digits + str(-total % 10)


GOLDEN_BANK = {
    "GB": "GOSO",
    "NL": "GOSO",
    "IE": "GOSO",
    "IT": "X",
    "DE": "50320700",
    "FR": "30788",
    "ES": "0233",
    "CH": "08788",
    "PL": "19100047",
    "CZ": "2280",
    "AE": "063",
    "BR": "38166000",
    "US": aba(),
    "JP": "0491",
    "SG": "7462",
    "HK": "394",
    "AU": "083-117",
    "CA": "00219-047",
    "IN": "GOSO0000412",
    "MX": "182",
}
BIC_LOCATION = {
    "US": "33",
    "GB": "2L",
    "DE": "FF",
    "FR": "PP",
    "CH": "ZZ",
    "NL": "2A",
    "IT": "MM",
    "ES": "MM",
    "IE": "2D",
    "PL": "PW",
    "CZ": "PP",
    "JP": "JT",
    "HK": "HH",
    "SG": "SG",
    "AU": "2S",
    "CA": "T2",
    "IN": "BB",
    "BR": "SP",
    "MX": "MM",
    "AE": "AD",
}


def iban(country: str, bank: str) -> str:
    length, _ = IBAN[country]
    bban = bank + pattern("#" * (length - 4 - len(bank)))
    if country == "BR":
        bban = bban[:-2] + "C1"
    number = "".join(str(int(c, 36)) for c in bban + country + "00")
    raw = f"{country}{98 - int(number) % 97:02d}{bban}"
    return " ".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def bank_account(country: str, golden: bool = False) -> str:
    """An account at Golden Socks, or at another bank, in the country's format."""
    bank = GOLDEN_BANK.get(country) if golden else None
    if country in IBAN:
        return iban(country, bank or pattern(IBAN[country][1]))
    match country:
        case "US":
            return f"{bank or aba()} {pattern('%#########')}"
        case "JP":
            return f"{bank or pattern('0%##')}-{pattern('###')}-{pattern('#######')}"
        case "SG":
            return f"{bank or pattern('7###')}-{pattern('###')}-{pattern('######')}"
        case "HK":
            return f"{bank or pattern('0%#')}-{pattern('###')}-{pattern('#########')}"
        case "AU":
            return f"{bank or pattern('0##-###')} {pattern('%#######')}"
        case "CA":
            return f"{bank or pattern('#####-0##')} {pattern('%######')}"
        case "IN":
            return f"{bank or pattern('????0######')} {pattern('%#############')}"
        case "MX":
            return clabe(bank or pattern("0##"))
    return pattern("%#########")


def person(country: str) -> tuple[str, str, bool]:
    """First name, last name, and whether she is a woman."""
    male, female, last, *female_last = NAMES[COUNTRIES[country].names]
    if rng.random() < 0.5:
        return rng.choice(male), rng.choice(last), False
    return rng.choice(female), rng.choice(female_last[0] if female_last else last), True


def city_of(country: str) -> tuple[str, str]:
    cities = COUNTRIES[country].cities
    return rng.choices(cities, weights=range(len(cities) * 2, 0, -2))[0]


def address(country: str, city: str | None = None) -> str:
    c = COUNTRIES[country]
    name, postcode = next((x for x in c.cities if x[0] == city), city_of(country))
    n = (
        pattern("%-%-%")
        if country == "JP"
        else str(rng.choice((rng.randint(1, 60), rng.randint(1, 400))))
    )
    return c.address.format(
        n=n, street=rng.choice(c.streets), city=name, postcode=pattern(postcode)
    )


# Markets -------------------------------------------------------------------


@dataclass(frozen=True)
class Instrument:
    asset_class: str
    currency: str
    venue: str
    # The price on the first and the last day: a random walk joins them.
    start: float
    end: float
    vol: float
    # Notional per unit of quantity, in the instrument's currency per point.
    multiplier: float
    decimals: int
    name: str
    sector: str = "Macro"


def equity(
    currency: str,
    venue: str,
    start: float,
    end: float,
    vol: float,
    name: str,
    sector: str,
) -> Instrument:
    return Instrument(
        "Equities",
        currency,
        venue,
        start,
        end,
        vol,
        1,
        0 if currency == "JPY" else 2,
        name,
        sector,
    )


# fmt: off
INSTRUMENTS = {
    "NVDA": equity("USD", "NASDAQ", 14.6, 182, 0.5, "NVIDIA", "Technology"),
    "AAPL": equity("USD", "NASDAQ", 125, 232, 0.25, "Apple", "Technology"),
    "MSFT": equity("USD", "NASDAQ", 239, 505, 0.24, "Microsoft", "Technology"),
    "AMZN": equity("USD", "NASDAQ", 85, 226, 0.32, "Amazon", "Consumer"),
    "GOOGL": equity("USD", "NASDAQ", 89, 205, 0.3, "Alphabet", "Media"),
    "META": equity("USD", "NASDAQ", 120, 735, 0.38, "Meta Platforms", "Media"),
    "TSLA": equity("USD", "NASDAQ", 108, 340, 0.55, "Tesla", "Consumer"),
    "JPM": equity("USD", "NYSE", 134, 295, 0.22, "JPMorgan Chase", "Financials"),
    "BAC": equity("USD", "NYSE", 33, 49, 0.25, "Bank of America", "Financials"),
    "GS": equity("USD", "NYSE", 343, 760, 0.25, "Goldman Sachs", "Financials"),
    "XOM": equity("USD", "NYSE", 110, 112, 0.22, "Exxon Mobil", "Energy"),
    "CVX": equity("USD", "NYSE", 179, 156, 0.22, "Chevron", "Energy"),
    "LLY": equity("USD", "NYSE", 365, 810, 0.3, "Eli Lilly", "Healthcare"),
    "JNJ": equity("USD", "NYSE", 177, 168, 0.15, "Johnson & Johnson", "Healthcare"),
    "SHEL": equity("GBP", "LSE", 23.5, 27.2, 0.2, "Shell", "Energy"),
    "ASML": equity("EUR", "Euronext", 600, 705, 0.35, "ASML", "Technology"),
    "SAP": equity("EUR", "XETRA", 97, 245, 0.28, "SAP", "Technology"),
    "AIR": equity("EUR", "Euronext", 111, 198, 0.27, "Airbus", "Aerospace & Defense"),
    "NESN": equity("CHF", "SIX", 113, 81, 0.16, "Nestlé", "Consumer"),
    "7203": equity("JPY", "JPX", 1800, 2750, 0.28, "Toyota Motor", "Transportation"),
    "EURUSD": Instrument("FX", "USD", "OTC", 1.07, 1.165, 0.07, 1, 5, "EUR/USD"),
    "GBPUSD": Instrument("FX", "USD", "OTC", 1.21, 1.345, 0.08, 1, 5, "GBP/USD"),
    "USDJPY": Instrument("FX", "JPY", "OTC", 131, 147.5, 0.1, 1, 3, "USD/JPY"),
    "USDCHF": Instrument("FX", "CHF", "OTC", 0.925, 0.797, 0.07, 1, 5, "USD/CHF"),
    "EURGBP": Instrument("FX", "GBP", "OTC", 0.885, 0.866, 0.05, 1, 5, "EUR/GBP"),
    "USDCZK": Instrument("FX", "CZK", "OTC", 22.6, 20.9, 0.08, 1, 4, "USD/CZK"),
    "US2Y": Instrument("Rates", "USD", "OTC", 99.6, 100.25, 0.015, 0.01, 3, "US 2Y"),
    "US10Y": Instrument("Rates", "USD", "OTC", 96.2, 98.4, 0.06, 0.01, 3, "US 10Y"),
    "UK10Y": Instrument("Rates", "GBP", "OTC", 97.1, 95.6, 0.07, 0.01, 3, "UK 10Y"),
    "DE10Y": Instrument("Rates", "EUR", "OTC", 99.1, 98.3, 0.05, 0.01, 3, "Bund 10Y"),
    "JP10Y": Instrument("Rates", "JPY", "OTC", 100.1, 97.4, 0.03, 0.01, 3, "JGB 10Y"),
    "IG-CDX": Instrument("Credit", "USD", "ICE", 100.6, 101.1, 0.02, 0.01, 3, "CDX IG"),
    "HY-CDX": Instrument("Credit", "USD", "ICE", 98.1, 106.4, 0.06, 0.01, 3, "CDX HY"),
    "EUR-IG": Instrument("Credit", "EUR", "OTC", 100.2, 101.0, 0.02, 0.01, 3,
                         "iTraxx Main"),
    "EUR-HY": Instrument("Credit", "EUR", "OTC", 96.8, 104.3, 0.06, 0.01, 3,
                         "iTraxx Crossover"),
    "EM-CORP": Instrument("Credit", "USD", "OTC", 92.3, 97.6, 0.07, 0.01, 3,
                          "EM corporate bonds"),
    "WTI": Instrument("Commodities", "USD", "CME", 80.3, 66.5, 0.35, 1000, 2, "WTI crude"),
    "BRENT": Instrument("Commodities", "USD", "ICE", 85.9, 69.8, 0.33, 1000, 2, "Brent"),
    "NATGAS": Instrument("Commodities", "USD", "CME", 4.48, 3.15, 0.6, 10000, 3,
                         "Natural gas"),
    "COPPER": Instrument("Commodities", "USD", "CME", 3.81, 4.92, 0.25, 25000, 4,
                         "Copper"),
    "XAUUSD": Instrument("Commodities", "USD", "OTC", 1830, 3660, 0.16, 1, 2, "Gold"),
}
# fmt: on
BY_CLASS: dict[str, list[str]] = defaultdict(list)
for _symbol, _instrument in INSTRUMENTS.items():
    BY_CLASS[_instrument.asset_class].append(_symbol)

PRICE_DAYS = business_days(date(2023, 1, 2), LAST_DAY)


def price_path(i: Instrument) -> dict[date, float]:
    """A random walk from the start price to the end price."""
    n = len(PRICE_DAYS) - 1
    step = i.vol / math.sqrt(252)
    walk = [0.0]
    for _ in range(n):
        walk.append(walk[-1] + rng.gauss(0, step))
    drift = math.log(i.end / i.start)
    return {
        day: i.start * math.exp(drift * k / n + walk[k] - walk[-1] * k / n)
        for k, day in enumerate(PRICE_DAYS)
    }


PRICES = {symbol: price_path(i) for symbol, i in INSTRUMENTS.items()}
STATIC_USD = {
    "USD": 1,
    "SGD": 0.77,
    "HKD": 0.128,
    "AUD": 0.66,
    "CAD": 0.72,
    "INR": 0.0114,
    "BRL": 0.18,
    "MXN": 0.054,
    "AED": 0.2723,
    "PLN": 0.27,
}


def usd_rate(currency: str, day: date) -> float:
    """US dollars for one unit of the currency on the day."""
    match currency:
        case "EUR":
            return PRICES["EURUSD"][day]
        case "GBP":
            return PRICES["GBPUSD"][day]
        case "JPY" | "CHF" | "CZK":
            return 1 / PRICES[f"USD{currency}"][day]
    return STATIC_USD[currency]


# Employees -----------------------------------------------------------------

LEVELS = (
    "Analyst",
    "Associate",
    "Vice President",
    "Executive Director",
    "Managing Director",
)
JUNIOR_TITLE = {
    "Global Investment Research": "Research Analyst",
    "Engineering": "Engineer",
    "Compliance": "Compliance Officer",
    "Risk": "Risk Manager",
    "Operations": "Operations Specialist",
}
TRADING_DESKS = (
    "FICC - FX",
    "FICC - Rates",
    "FICC - Credit",
    "Equities - Cash",
    "Equities - Derivatives",
    "Commodities",
    "Prime Services",
)
# fmt: off
TEAMS = {
    "Global Banking & Markets": {"Client Coverage": 250, "Equities - Cash": 80,
                                 "FICC - FX": 70, "FICC - Rates": 70, "FICC - Credit": 60,
                                 "Equities - Derivatives": 60, "Prime Services": 60,
                                 "Commodities": 50},
    "Asset & Wealth Management": {"Private Wealth": 220, "Portfolio Management": 130},
    "Platform Solutions": {"Transaction Banking": 130, "Client Onboarding": 70},
    "Global Investment Research": {"Research": 200},
    "Risk": {"Market Risk": 120, "Operational Risk": 80},
    "Compliance": {"AML": 130, "Surveillance": 70},
    "Engineering": {"Platform Engineering": 300, "Cybersecurity": 100},
    "Operations": {"Settlements": 150, "Client Onboarding": 100},
}
OFFICES = {"New York": ("US", "NYC"), "Dallas": ("US", "DAL"),
           "Salt Lake City": ("US", "SLC"), "London": ("GB", "LDN"),
           "Paris": ("FR", "PAR"), "Frankfurt": ("DE", "FRA"), "Zurich": ("CH", "ZRH"),
           "Warsaw": ("PL", "WAW"), "Prague": ("CZ", "PRG"), "Tokyo": ("JP", "TYO"),
           "Hong Kong": ("HK", "HKG"), "Singapore": ("SG", "SIN")}
DIVISION_OFFICES = {
    "Global Banking & Markets": {"New York": 40, "London": 30, "Frankfurt": 5, "Paris": 5,
                                 "Tokyo": 8, "Hong Kong": 7, "Singapore": 5},
    "Asset & Wealth Management": {"New York": 35, "London": 20, "Zurich": 20,
                                  "Hong Kong": 10, "Singapore": 10, "Paris": 5},
    "Platform Solutions": {"New York": 40, "Dallas": 20, "London": 25, "Frankfurt": 15},
    "Global Investment Research": {"New York": 45, "London": 30, "Tokyo": 10,
                                   "Hong Kong": 10, "Frankfurt": 5},
    "Risk": {"New York": 30, "Dallas": 20, "London": 25, "Warsaw": 25},
    "Compliance": {"New York": 30, "London": 25, "Warsaw": 25, "Prague": 10,
                   "Singapore": 10},
    "Engineering": {"Dallas": 20, "Salt Lake City": 20, "New York": 15, "London": 10,
                    "Warsaw": 20, "Prague": 10, "Tokyo": 5},
    "Operations": {"Salt Lake City": 35, "Dallas": 20, "Warsaw": 25, "Prague": 10,
                   "Singapore": 10},
}
TRADING_OFFICES = {"New York": 45, "London": 35, "Tokyo": 10, "Hong Kong": 10}
LOCATION_PAY = {"US": 1.0, "GB": 0.9, "CH": 1.1, "FR": 0.8, "DE": 0.8, "JP": 0.85,
                "HK": 0.95, "SG": 0.9, "PL": 0.45, "CZ": 0.42}
# fmt: on


@dataclass
class Employee:
    division: str
    team: str
    level: int
    office: str
    first: str
    last: str
    female: bool
    id: str = ""
    manager: Employee | None = None

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"

    @property
    def title(self) -> str:
        if self.level == 0 and self.division in JUNIOR_TITLE:
            return JUNIOR_TITLE[self.division]
        return LEVELS[self.level]


def national_id(country: str, born: date, female: bool) -> str:
    match country:
        case "US":
            return f"{rng.randint(100, 665)}-{rng.randint(10, 99)}-{pattern('%###')}"
        case "GB":
            prefix = rng.choice(("AB", "CE", "GH", "JK", "LM", "NP", "PR", "SR", "TW"))
            return f"{prefix} {pattern('## ## ##')} {rng.choice('ABCD')}"
        case "FR":
            s = f"{2 if female else 1}{born:%y%m}75{rng.randint(101, 120)}{pattern('###')}"
            key = 97 - int(s) % 97
            return f"{s[0]} {s[1:3]} {s[3:5]} {s[5:7]} {s[7:10]} {s[10:]} {key:02d}"
        case "CH":
            return f"756.{pattern('####')}.{pattern('####')}.{pattern('##')}"
        case "PL":
            month = born.month + (20 if born.year >= 2000 else 0)
            serial = f"{pattern('###')}{rng.choice('02468' if female else '13579')}"
            s = f"{born:%y}{month:02d}{born:%d}{serial}"
            total = sum(int(c) * w for c, w in zip(s, (1, 3, 7, 9) * 3, strict=False))
            return s + str(-total % 10)
        case "CZ":
            month = born.month + (50 if female else 0)
            while True:
                base = int(f"{born:%y}{month:02d}{born:%d}{pattern('###')}")
                check = -base * 10 % 11
                if check < 10:
                    s = f"{base * 10 + check:010d}"
                    return f"{s[:6]}/{s[6:]}"
        case "JP":
            return pattern("%###########")
        case "HK":
            return (
                f"{rng.choice('ACDEGHKPRVZ')}{pattern('######')}({rng.randint(0, 9)})"
            )
        case "SG":
            return (
                f"{'T' if born.year >= 2000 else 'S'}{pattern('#######')}{pattern('?')}"
            )
    return pattern("%##########")


def generate_employees() -> list[Employee]:
    employees: list[Employee] = []
    for division, teams in TEAMS.items():
        head = None
        for team, headcount in teams.items():
            offices = (
                TRADING_OFFICES if team in TRADING_DESKS else DIVISION_OFFICES[division]
            )
            levels = [4] + rng.choices(
                range(5), weights=(30, 28, 25, 11, 4), k=headcount - 1
            )
            members = []
            for level in sorted(levels, reverse=True):
                office = weighted(offices)
                first, last, female = person(OFFICES[office][0])
                members.append(
                    Employee(division, team, level, office, first, last, female)
                )
            team_head = members[0]
            if head is None:
                head = team_head
            else:
                team_head.manager = head
            for member in members[1:]:
                seniors = [m for m in members if m.level > member.level]
                local = [m for m in seniors if m.office == member.office]
                member.manager = rng.choice(local or [team_head])
            employees.extend(members)
    # IDs in hiring order, not by team.
    rng.shuffle(employees)
    for n, employee in enumerate(employees, 1):
        employee.id = f"EMP-{n:05d}"
    return employees


def employee_rows(employees: list[Employee]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    emails: set[str] = set()
    devices = rng.sample(range(100000, 999999), len(employees))
    division_codes = {d: n for n, d in enumerate(TEAMS, 1)}
    for employee, device in zip(employees, devices, strict=True):
        country = OFFICES[employee.office][0]
        age = rng.randint(
            *((22, 27), (26, 32), (30, 42), (36, 50), (41, 60))[employee.level]
        )
        born = date(TODAY.year - age, rng.randint(1, 12), rng.randint(1, 28))
        local = f"{slug(employee.first)}.{slug(employee.last)}"
        email, n = f"{local}@goldensocks.com", 1
        while email in emails:
            n += 1
            email = f"{local}{n}@goldensocks.com"
        emails.add(email)
        base = (115000, 165000, 225000, 285000, 400000)[employee.level]
        base *= LOCATION_PAY[country] * rng.uniform(0.92, 1.1)
        rating = weighted({"EXCEEDS": 20, "MEETS": 65, "DEVELOPING": 15})
        bonus_rate = (
            (0.4, 0.6, 0.8, 1.2, 2.0)
            if employee.division == "Global Banking & Markets"
            else (0.15, 0.2, 0.3, 0.45, 0.8)
        )[employee.level]
        bonus = (
            base * bonus_rate * {"EXCEEDS": 1.3, "MEETS": 1, "DEVELOPING": 0.5}[rating]
        )
        privileged = employee.team == "Cybersecurity" or (
            employee.division == "Engineering"
            and employee.level >= 1
            and rng.random() < 0.4
        )
        if (employee.division in ("Compliance", "Risk") and employee.level >= 2) or (
            employee.team == "Cybersecurity" or employee.level == 4
        ):
            clearance = "PRIVILEGED"
        elif employee.level == 0 and employee.division in ("Operations", "Engineering"):
            clearance = "LOW"
        else:
            clearance = "STANDARD"
        team_index = list(TEAMS[employee.division]).index(employee.team)
        office_code = OFFICES[employee.office][1]
        rows.append(
            {
                "employee_id": employee.id,
                "name": employee.name,
                "division": employee.division,
                "desk_or_team": employee.team,
                "title": employee.title,
                "office": employee.office,
                "manager_id": employee.manager.id if employee.manager else None,
                "email": email,
                "phone": pattern(COUNTRIES[country].phone),
                "cost_center": f"{division_codes[employee.division]}{team_index + 1}"
                f"{list(OFFICES).index(employee.office):02d}-{office_code}",
                "clearance_level": clearance,
                "employment_status": "ON_LEAVE" if rng.random() < 0.02 else "ACTIVE",
                "salary_band": f"B{employee.level + 1}",
                "base_salary_usd": int(round(base, -2)),
                "bonus_usd": int(round(bonus, -2)),
                "home_address": address(country, employee.office),
                "national_id": national_id(country, born, employee.female),
                "device_id": f"GSL-{device}",
                "privileged_access": privileged,
                "api_token": "gsk_"
                + "".join(rng.choices(string.ascii_lowercase + string.digits, k=40))
                if privileged
                else None,
                "performance_rating": rating,
            }
        )
    return rows


# Clients and accounts ------------------------------------------------------

# fmt: off
CLIENT_TYPES = {"Corporate": 30, "UHNW": 20, "Asset Manager": 14, "Hedge Fund": 11,
                "Family Office": 11, "Pension Fund": 7.6, "Insurance": 6, "Sovereign": 0.4}
# The median and spread of a client's assets at the bank, in USD.
CLIENT_SIZE = {"Sovereign": (8e9, 0.8), "Pension Fund": (2e9, 1.0),
               "Insurance": (1.5e9, 1.0), "Asset Manager": (1e9, 1.2),
               "Hedge Fund": (4e8, 1.1), "Family Office": (1.5e8, 0.9),
               "UHNW": (4e7, 0.9), "Corporate": (8e7, 1.3)}
ACCOUNT_TYPES = {
    "Hedge Fund": {"Prime Brokerage": 40, "Margin": 25, "Trading": 20, "Custody": 10,
                   "Liquidity": 5},
    "Asset Manager": {"Custody": 45, "Trading": 30, "Liquidity": 15, "Margin": 10},
    "Pension Fund": {"Custody": 55, "Trading": 20, "Liquidity": 25},
    "Insurance": {"Custody": 55, "Trading": 20, "Liquidity": 25},
    "Sovereign": {"Custody": 50, "Trading": 25, "Liquidity": 25},
    "Corporate": {"Operating Cash": 50, "Liquidity": 30, "Trading": 20},
    "Family Office": {"Wealth": 35, "Custody": 25, "Margin": 15, "Liquidity": 15,
                      "Trading": 10},
    "UHNW": {"Wealth": 55, "Custody": 15, "Liquidity": 20, "Margin": 10},
}
# How much of an account's assets sit in cash, and how much of the client's
# assets each account type holds.
CASH_SHARE = {"Operating Cash": 1.0, "Liquidity": 0.9, "Custody": 0.03,
              "Prime Brokerage": 0.1, "Margin": 0.08, "Trading": 0.15, "Wealth": 0.1}
ACCOUNT_SIZE = {"Custody": 5, "Prime Brokerage": 3, "Wealth": 3, "Margin": 1.5,
                "Trading": 1, "Liquidity": 1, "Operating Cash": 0.6}
RELATIONSHIP = {"UHNW": ("Asset & Wealth Management", "Private Wealth"),
                "Family Office": ("Asset & Wealth Management", "Private Wealth"),
                "Corporate": ("Platform Solutions", "Transaction Banking")}
REGION_OFFICES = {"Americas": ("New York", "Dallas"),
                  "Europe": ("London", "Frankfurt", "Paris", "Zurich"),
                  "Asia": ("Hong Kong", "Singapore", "Tokyo")}
PREFIXES = ("North", "Silver", "Iron", "Cedar", "Harbor", "Summit", "Granite", "Aspen",
            "Beacon", "Falcon", "Meridian", "Oak", "Pine", "River", "Stone", "Willow",
            "Atlas", "Orion", "Polar", "Crimson", "Sterling", "Highland", "Lake", "Maple",
            "Redwood", "Copper", "Ember", "Juniper", "Lantern", "Marble", "Rowan",
            "Saffron", "Tidal", "Vesper", "Wren", "Alder", "Calder", "Fair", "Glen",
            "Hawthorne", "Kestrel", "Lark", "Morrow", "Oakmont", "Pemberton", "Sable",
            "Thorn", "Vale", "West", "East", "Blackwater", "Clear", "Elm", "Bright")
SUFFIXES = ("bridge", "field", "stone", "wood", "gate", "ridge", "point", "haven",
            "crest", "view", "brook", "hill", "ford", "mere", "wick", "shore", "peak",
            "worth", "dale", "moor")
SECTOR_NOUNS = {
    "Technology": ("Systems", "Software", "Semiconductors", "Networks", "Technologies"),
    "Healthcare": ("Pharma", "Biosciences", "Medical", "Health"),
    "Energy": ("Energy", "Petroleum", "Power", "Renewables"),
    "Utilities": ("Utilities", "Water", "Grid"),
    "Consumer": ("Foods", "Brands", "Retail", "Beverages"),
    "Financials": ("Finance", "Leasing", "Payments"),
    "Real Estate": ("Properties", "Realty", "Estates"),
    "Transportation": ("Logistics", "Shipping", "Airlines", "Rail"),
    "Materials": ("Chemicals", "Steel", "Mining", "Materials"),
    "Industrials": ("Industries", "Engineering", "Manufacturing", "Machinery"),
    "Aerospace & Defense": ("Aerospace", "Defense Systems", "Avionics"),
    "Media": ("Media", "Studios", "Publishing", "Entertainment"),
    "Telecommunications": ("Telecom", "Communications", "Mobile"),
}
# fmt: on


def compound() -> str:
    return rng.choice(PREFIXES) + rng.choice(SUFFIXES)


def client_name(kind: str, country: str, sector: str, last: str) -> str:
    legal = rng.choice(COUNTRIES[country].legal)
    match kind:
        case "Hedge Fund":
            style = rng.choice(
                ("Capital", "Capital Management", "Partners", "Investment Partners")
            )
            return f"{compound()} {style} {'LP' if country in ('US', 'CA') else legal}"
        case "Asset Manager":
            style = rng.choice(
                (
                    "Asset Management",
                    "Investors",
                    "Investment Management",
                    "Global Advisors",
                )
            )
            return f"{compound()} {style} {legal}"
        case "Insurance":
            return f"{compound()} {rng.choice(('Life', 'Re', 'Assurance', 'Mutual'))} {legal}"
        case "Pension Fund":
            return f"{compound()} {
                rng.choice(('Pension Fund', 'Retirement Fund', 'Pension Scheme'))
            }"
        case "Sovereign":
            style = rng.choice(
                (
                    "Investment Authority",
                    "Future Fund",
                    "Reserve Fund",
                    "Investment Corporation",
                )
            )
            return f"{COUNTRIES[country].name} {style}"
        case "Family Office":
            return f"{last} {rng.choice(('Family Office', 'Family Holdings', 'Family Trust'))}"
        case "UHNW":
            return last
    return f"{compound()} {rng.choice(SECTOR_NOUNS[sector])} {legal}"


@dataclass
class Client:
    id: str
    kind: str
    country: str
    city: str
    name: str
    sector: str
    risk: str
    sanctions: str
    status: str
    kyc: str
    since: date
    rm: Employee
    contact: str
    owner: str
    signatories: list[str]
    accounts: list[Account] = field(default_factory=list)
    beneficiaries: list[tuple[str, str, str]] = field(default_factory=list)
    rating: str = ""


@dataclass
class Account:
    id: str
    client: Client
    kind: str
    jurisdiction: str
    currency: str
    opened: date
    status: str
    flag: str
    cash: float
    portfolio: float
    exposure: float
    margin: float
    number: str
    bank_account: str
    signatory: str


def generate_clients(employees: list[Employee]) -> list[Client]:
    rms: dict[str, list[Employee]] = defaultdict(list)
    for e in employees:
        if e.team in ("Client Coverage", "Private Wealth", "Transaction Banking") and (
            e.level >= 1
        ):
            rms[e.team].append(e)
    names: set[str] = set()
    clients = []
    weights = {code: c.weight for code, c in COUNTRIES.items()}
    for n in range(1, 8001):
        kind = weighted(CLIENT_TYPES)
        country = weighted(weights)
        if kind == "Sovereign":
            # One sovereign fund per country.
            taken = {c.country for c in clients if c.kind == "Sovereign"}
            free = {code: w for code, w in weights.items() if code not in taken}
            if free:
                country = weighted(free)
            else:
                kind = "Pension Fund"
        while True:
            first, last, _ = person(country)
            sector = (
                "Financials"
                if kind
                in (
                    "Asset Manager",
                    "Hedge Fund",
                    "Insurance",
                    "Pension Fund",
                    "Family Office",
                )
                else "Government"
                if kind == "Sovereign"
                else "Private Individuals"
                if kind == "UHNW"
                else rng.choice(list(SECTOR_NOUNS))
            )
            # Family offices often carry the founder's full name: surnames
            # alone run out in the big countries.
            full = kind == "UHNW" or (kind == "Family Office" and rng.random() < 0.6)
            name = client_name(
                kind, country, sector, f"{first} {last}" if full else last
            )
            if name not in names:
                break
        names.add(name)
        score = (
            {
                "UHNW": 2,
                "Hedge Fund": 2,
                "Family Office": 2,
                "Corporate": 1,
                "Sovereign": 1,
            }.get(kind, 0)
            + COUNTRIES[country].risk
            + rng.randint(0, 2)
        )
        risk = "LOW" if score < 2 else "MEDIUM" if score < 4 else "HIGH"
        sanctions = (
            "REVIEW" if rng.random() < (0.03 if risk == "HIGH" else 0.004) else "CLEAR"
        )
        onboarding = rng.random() < 0.07
        if onboarding:
            status, kyc = "ONBOARDING", "PENDING_REVIEW"
        else:
            restricted = sanctions == "REVIEW" or (
                risk == "HIGH" and rng.random() < 0.12
            )
            status = "RESTRICTED" if restricted else "ACTIVE"
            overdue = rng.random() < (0.25 if risk == "HIGH" else 0.05)
            kyc = "REVIEW_DUE" if overdue else "APPROVED"
        division, team = RELATIONSHIP.get(
            kind, ("Global Banking & Markets", "Client Coverage")
        )
        region = COUNTRIES[country].region
        pool = rms[team]
        local = [e for e in pool if e.office in REGION_OFFICES[region]]
        contact = " ".join(person(country)[:2])
        if kind == "UHNW":
            owner = contact = name
        elif kind == "Family Office":
            owner = f"{first} {last}"
        elif kind == "Sovereign":
            owner = f"Government of {COUNTRIES[country].name}"
        elif kind in ("Pension Fund", "Insurance") or rng.random() < 0.4:
            owner = "Widely held, no single beneficial owner"
        else:
            owner = " ".join(person(country)[:2])
        officers = [" ".join(person(country)[:2]) for _ in range(rng.randint(0, 2))]
        signatories = [
            p
            for p in (contact, owner, *officers)
            if not p.startswith(("Widely", "Government"))
        ]
        since = (
            date(2026, rng.randint(1, 9), rng.randint(1, 28))
            if onboarding
            else date(rng.randint(2005, 2025), rng.randint(1, 12), rng.randint(1, 28))
        )
        clients.append(
            Client(
                id=f"CLT-{n:06d}",
                kind=kind,
                country=country,
                city=city_of(country)[0],
                name=name,
                sector=sector,
                risk=risk,
                sanctions=sanctions,
                status=status,
                kyc=kyc,
                since=since,
                rm=rng.choice(local or pool),
                contact=contact,
                owner=owner,
                signatories=signatories,
            )
        )
    return clients


def generate_accounts(clients: list[Client]) -> list[Account]:
    active = [c for c in clients if c.status != "ONBOARDING"]
    extra = {
        "Hedge Fund": 3,
        "Asset Manager": 2.5,
        "Sovereign": 3,
        "Pension Fund": 2,
        "Insurance": 2,
        "Family Office": 2.2,
        "Corporate": 1.8,
        "UHNW": 1.6,
    }
    counts = dict.fromkeys((c.id for c in active), 1)
    picks = rng.choices(
        active, weights=[extra[c.kind] for c in active], k=15000 - len(active)
    )
    for c in picks:
        counts[c.id] += 1
    hubs = {"US": 40, "GB": 30, "CH": 15, "SG": 10, "HK": 5}
    accounts = []
    for client in active:
        size = rng.lognormvariate(
            math.log(CLIENT_SIZE[client.kind][0]), CLIENT_SIZE[client.kind][1]
        )
        types = ACCOUNT_TYPES[client.kind]
        kinds = [max(types, key=types.__getitem__)]
        kinds += [weighted(types) for _ in range(counts[client.id] - 1)]
        shares = [ACCOUNT_SIZE[k] * rng.uniform(0.5, 1.5) for k in kinds]
        client.rating = rng.choice(
            {
                "LOW": ("A+", "A", "A-"),
                "MEDIUM": ("BBB+", "BBB", "BBB-"),
                "HIGH": ("BB+", "BB", "BB-"),
            }[client.risk]
        )
        for kind, share in zip(kinds, shares, strict=True):
            jurisdiction = client.country if rng.random() < 0.8 else weighted(hubs)
            local = COUNTRIES[jurisdiction].currency
            currency = weighted({local: 60, "USD": 30, "EUR": 10})
            opened = client.since + timedelta(
                rng.randint(0, max(1, (TODAY - client.since).days - 60))
            )
            opened = add_business_days(opened - timedelta(1), 1)
            if client.sanctions == "REVIEW":
                flag = "LEGAL_HOLD"
            elif client.status == "RESTRICTED" or (
                client.risk == "HIGH" and client.kyc == "REVIEW_DUE"
            ):
                flag = "RISK_REVIEW"
            else:
                flag = "NONE"
            closed = flag == "NONE" and rng.random() < 0.04
            amount = 0.0 if closed else size * share / sum(shares)
            cash = amount * CASH_SHARE[kind]
            portfolio = amount - cash
            exposure = portfolio * {
                "Prime Brokerage": rng.uniform(0.2, 0.6),
                "Margin": rng.uniform(0.1, 0.4),
                "Trading": rng.uniform(0, 0.1),
            }.get(kind, 0)
            margin = exposure * {
                "Prime Brokerage": rng.uniform(0.25, 0.5),
                "Margin": rng.uniform(0.3, 0.5),
                "Trading": 0.2,
            }.get(kind, 0)
            accounts.append(
                Account(
                    id="",
                    client=client,
                    kind=kind,
                    jurisdiction=jurisdiction,
                    currency=currency,
                    opened=opened,
                    status="CLOSED"
                    if closed
                    else "OPEN"
                    if flag == "NONE"
                    else "RESTRICTED",
                    flag=flag,
                    cash=cash,
                    portfolio=portfolio,
                    exposure=exposure,
                    margin=margin,
                    number="",
                    bank_account=bank_account(jurisdiction, golden=True),
                    signatory=rng.choice(client.signatories),
                )
            )
            client.accounts.append(accounts[-1])
    numbers = rng.sample(range(10**9, 10**10), len(accounts))
    for n, (account, number) in enumerate(zip(accounts, numbers, strict=True), 1):
        account.id = f"ACC-{n:07d}"
        account.number = str(number)
    return accounts


def client_notes(c: Client, compliance: list[Employee]) -> str:
    notes = []
    if c.status == "ONBOARDING":
        notes.append(
            f"Onboarding opened {c.since}; awaiting certified incorporation "
            "documents and UBO declaration."
        )
    if c.sanctions == "REVIEW":
        officer = rng.choice(compliance)
        notes.append(
            f"Name-screening hit on a related party under review by {officer.name} "
            f"({officer.id}); no new business until cleared."
        )
    if c.kyc == "REVIEW_DUE":
        notes.append(
            "Periodic KYC review overdue; RM chasing updated ownership documents."
        )
    if c.risk == "HIGH":
        notes.append(
            "Enhanced due diligence: complex ownership through holding entities "
            "in several jurisdictions."
        )
    if c.kind == "Hedge Fund" and len(c.accounts) > 1:
        notes.append(
            f"Prime brokerage across {len(c.accounts)} accounts; margin terms "
            "reviewed quarterly."
        )
    if c.kind == "Corporate":
        notes.append(
            f"Uses transaction banking for payroll and supplier payments in "
            f"{COUNTRIES[c.country].currency}."
        )
    if not notes:
        notes.append(
            f"Annual review completed {date(2026, rng.randint(1, 9), 15)}; "
            "no material issues."
        )
    return " ".join(notes[:2])


def client_rows(
    clients: list[Client], employees: list[Employee]
) -> list[dict[str, Any]]:
    compliance = [e for e in employees if e.team == "AML" and e.level >= 1]
    aum = {c.id: sum(a.cash + a.portfolio for a in c.accounts) for c in clients}
    ranked = sorted(aum, key=aum.__getitem__, reverse=True)
    rank = {client_id: n / len(ranked) for n, client_id in enumerate(ranked)}
    rows: list[dict[str, Any]] = []
    for c in clients:
        position = rank[c.id] if aum[c.id] else 1
        tier = (
            "Strategic"
            if position < 0.05
            else "Core"
            if position < 0.25
            else "Growth"
            if position < 0.6
            else "Standard"
        )
        exposure = sum(a.exposure for a in c.accounts)
        limit = (
            exposure / rng.uniform(0.45, 0.85)
            if exposure
            else (rng.uniform(5e6, 5e7) if c.kind == "Corporate" and c.accounts else 0)
        )
        revenue = (
            rng.lognormvariate(math.log(1.5e9), 1.2)
            if c.kind == "Corporate"
            else aum[c.id]
            * {"Asset Manager": 0.007, "Hedge Fund": 0.035, "Insurance": 0.15}.get(
                c.kind, 0.05
            )
        )
        domain = (
            rng.choice(("gmail.com", "outlook.com", "icloud.com", "proton.me"))
            if c.kind == "UHNW"
            else slug("".join(c.name.split()[:2])) + COUNTRIES[c.country].tld
        )
        first, *rest = c.contact.split()
        rows.append(
            {
                "client_id": c.id,
                "client_name": c.name,
                "client_type": c.kind,
                "country": COUNTRIES[c.country].name,
                "country_code": c.country,
                "city": c.city,
                "sector": c.sector,
                "relationship_division": c.rm.division,
                "relationship_tier": tier,
                "onboarding_status": c.status,
                "risk_rating": c.risk,
                "kyc_status": c.kyc,
                "sanctions_screening": c.sanctions,
                "primary_rm_id": c.rm.id,
                "aum_usd_mn": aum[c.id] / 1e6,
                "credit_limit_usd_mn": limit / 1e6,
                "annual_revenue_usd_mn": revenue / 1e6,
                "tax_id": pattern(COUNTRIES[c.country].tax_id),
                "legal_address": address(c.country, c.city),
                "contact_name": c.contact,
                "contact_email": f"{slug(first)}.{slug(''.join(rest))}@{domain}",
                "contact_phone": pattern(COUNTRIES[c.country].phone),
                "beneficial_owner": c.owner,
                "internal_notes": client_notes(c, compliance),
            }
        )
    return rows


def account_rows(accounts: list[Account]) -> list[dict[str, Any]]:
    return [
        {
            "account_id": a.id,
            "client_id": a.client.id,
            "account_type": a.kind,
            "currency": a.currency,
            "jurisdiction": a.jurisdiction,
            "opening_date": a.opened,
            "status": a.status,
            "cash_balance_usd": a.cash,
            "credit_exposure_usd": a.exposure,
            "margin_requirement_usd": a.margin,
            "portfolio_value_usd": a.portfolio,
            "internal_rating": a.client.rating,
            "account_number": a.number,
            "swift_bic": f"GOSO{a.jurisdiction}{BIC_LOCATION[a.jurisdiction]}",
            "iban_or_local_account": a.bank_account,
            "authorized_signatory": a.signatory,
            "restriction_flag": a.flag,
        }
        for a in accounts
    ]


# Trades --------------------------------------------------------------------

# fmt: off
TRADE_CLASSES = {
    "Hedge Fund": {"Equities": 45, "FX": 15, "Rates": 15, "Credit": 15, "Commodities": 10},
    "Asset Manager": {"Equities": 50, "Rates": 20, "Credit": 15, "FX": 15},
    "Pension Fund": {"Rates": 40, "Credit": 30, "Equities": 20, "FX": 10},
    "Insurance": {"Rates": 40, "Credit": 30, "Equities": 20, "FX": 10},
    "Sovereign": {"Rates": 40, "FX": 30, "Equities": 20, "Commodities": 10},
    "Corporate": {"FX": 70, "Rates": 20, "Commodities": 10},
    "Family Office": {"Equities": 65, "FX": 15, "Rates": 10, "Commodities": 10},
    "UHNW": {"Equities": 75, "FX": 15, "Commodities": 10},
}
TRADE_SIZE = {"Hedge Fund": 5e6, "Asset Manager": 8e6, "Pension Fund": 15e6,
              "Insurance": 10e6, "Sovereign": 25e6, "Corporate": 3e6,
              "Family Office": 1e6, "UHNW": 3e5}
TRADE_WEIGHT = {"Hedge Fund": 10, "Asset Manager": 5, "Sovereign": 3, "Pension Fund": 2,
                "Insurance": 2, "Corporate": 1.5, "Family Office": 1.5, "UHNW": 1}
DESKS = {"FX": "FICC - FX", "Rates": "FICC - Rates", "Credit": "FICC - Credit",
         "Commodities": "Commodities"}
CCPS = {"NYSE": "NSCC", "NASDAQ": "NSCC", "LSE": "LCH Ltd", "Euronext": "LCH SA",
        "XETRA": "Eurex Clearing", "SIX": "SIX x-clear", "JPX": "JSCC",
        "CME": "CME Clearing", "ICE": "ICE Clear"}
DEALERS = ("Halvorsen Bank AG", "Marston Wade Securities", "Banque Delorme",
           "Kirinbridge Securities", "Northcastle Capital Markets", "Stavros & Lyle",
           "Aldermoor Bank plc", "Vantressa Securities", "Corvane Markets",
           "Heidelberg Landesbank", "Tamsin Pryce & Co.", "Orinoco Banco")
# Trading hours in UTC, by the instrument's currency.
HOURS = {"USD": (13, 20), "JPY": (0, 6)}
TRADING_OFFICE = {"USD": ("New York",), "JPY": ("Tokyo", "Hong Kong")}
SPREAD_BPS = {"Equities": 3, "FX": 1, "Rates": 1.5, "Credit": 4, "Commodities": 5}
# fmt: on


def trade_notional(symbol: str, price: float, quantity: int, day: date) -> float:
    i = INSTRUMENTS[symbol]
    if i.asset_class == "FX":
        base = symbol[:3]
        return quantity * usd_rate(base, day)
    return quantity * price * i.multiplier * usd_rate(i.currency, day)


def trade_quantity(symbol: str, price: float, notional: float, day: date) -> int:
    i = INSTRUMENTS[symbol]
    if i.asset_class == "FX":
        return max(100000, int(round(notional / usd_rate(symbol[:3], day), -5)))
    units = notional / (price * i.multiplier * usd_rate(i.currency, day))
    if i.asset_class in ("Rates", "Credit"):
        return max(1000000, int(round(units, -6)))
    if symbol == "XAUUSD":
        return max(100, int(round(units, -2)))
    return max(1, round(units))


def generate_trades(
    accounts: list[Account], employees: list[Employee]
) -> list[dict[str, Any]]:
    eligible = [
        a
        for a in accounts
        if a.status == "OPEN"
        and a.kind in ("Trading", "Prime Brokerage", "Margin", "Custody", "Wealth")
    ]
    weights = [TRADE_WEIGHT[a.client.kind] * ACCOUNT_SIZE[a.kind] for a in eligible]
    traders: dict[tuple[str, str], list[Employee]] = defaultdict(list)
    for e in employees:
        if e.team in TRADING_DESKS and e.level <= 3:
            traders[e.team, e.office].append(e)
            traders[e.team, ""].append(e)
    heads = {e.team: e for e in employees if e.team in TRADING_DESKS and e.level == 4}
    days = business_days(date(2026, 4, 6), LAST_DAY)
    trades: list[dict[str, Any]] = []
    for account in rng.choices(eligible, weights=weights, k=60000):
        client = account.client
        asset_class = weighted(TRADE_CLASSES[client.kind])
        symbol = rng.choice(BY_CLASS[asset_class])
        i = INSTRUMENTS[symbol]
        if asset_class == "Equities":
            desk = (
                "Prime Services"
                if account.kind == "Prime Brokerage" and rng.random() < 0.6
                else weighted({"Equities - Cash": 75, "Equities - Derivatives": 25})
            )
        else:
            desk = DESKS[asset_class]
        day = rng.choice(days)
        start, end = HOURS.get(i.currency, (7, 16))
        moment = datetime.combine(
            day, time(rng.randint(start, end - 1), rng.randint(0, 59))
        )
        price = PRICES[symbol][day] * (1 + rng.gauss(0, i.vol / math.sqrt(252) / 3))
        price = round(price, i.decimals)
        size = TRADE_SIZE[client.kind] * rng.lognormvariate(0, 0.9)
        quantity = trade_quantity(symbol, price, min(size, 1.5e9), day)
        notional = trade_notional(symbol, price, quantity, day)
        office = rng.choice(TRADING_OFFICE.get(i.currency, ("London",)))
        trader = rng.choice(traders[desk, office] or traders[desk, ""])
        if client.kind == "Corporate":
            strategy = "Hedge" if rng.random() < 0.8 else "Liquidity"
        elif desk == "Prime Services":
            strategy = "Financing" if rng.random() < 0.6 else "Client Flow"
        elif desk == "Equities - Cash" and rng.random() < 0.35:
            strategy = "Execution"
        else:
            strategy = "Client Flow"
        settle = (
            1
            if (i.asset_class == "Equities" and i.currency == "USD")
            or (
                i.asset_class in ("Credit", "Commodities")
                or symbol in ("US2Y", "US10Y", "UK10Y")
            )
            else 2
        )
        settlement = add_business_days(day, settle)
        vol = i.vol / math.sqrt(252)
        street = i.venue == "OTC" and strategy in ("Hedge", "Execution", "Liquidity")
        trades.append(
            {
                "client_id": client.id,
                "account_id": account.id,
                "desk": desk,
                "asset_class": asset_class,
                "instrument": symbol,
                "side": rng.choice(("BUY", "SELL")),
                "quantity": quantity,
                "price": f"{price:.{i.decimals}f}",
                "notional_usd": notional,
                "currency": i.currency,
                "trade_timestamp": moment,
                "settlement_date": settlement,
                "trader_id": trader.id,
                "venue": i.venue,
                "pnl_usd": notional * rng.gauss(SPREAD_BPS[asset_class], 2) / 1e4,
                "var_1d_usd": notional * vol * 2.33,
                "status": "SETTLED" if settlement < TODAY else "BOOKED",
                "strategy": strategy,
                "counterparty": (
                    CCPS[i.venue]
                    if i.venue != "OTC"
                    else rng.choice(DEALERS)
                    if street
                    else client.name
                ),
                "internal_comment": None,
                "_head": heads[desk],
                "_account": account,
            }
        )
    trades.sort(key=lambda t: t["trade_timestamp"])
    for n, t in enumerate(trades, 1):
        t["trade_id"] = f"TRD-{n:08d}"
    for n, t in enumerate(trades):
        head, account = t.pop("_head"), t.pop("_account")
        others = [
            a
            for a in account.client.accounts
            if a is not account and a.status == "OPEN"
        ]
        if rng.random() < 0.008 and others and n + 1 < len(trades):
            t["status"] = "CANCELLED"
            t["pnl_usd"] = 0
            t["internal_comment"] = (
                f"Booked to the wrong account; cancelled and rebooked "
                f"on {rng.choice(others).id}."
            )
        elif t["trade_timestamp"].date() == LAST_DAY and rng.random() < 0.4:
            t["status"] = "PENDING"
        elif t["notional_usd"] > 1e8:
            t["internal_comment"] = (
                f"Large notional; pre-trade limit check approved by {head.name}."
            )
        elif t["strategy"] == "Execution":
            t["internal_comment"] = (
                f"Worked via VWAP algo over {rng.randint(1, 6)} hours."
            )
        elif t["strategy"] == "Hedge" and t["asset_class"] == "FX":
            quarter = (t["settlement_date"].month - 1) // 3 + 1
            t["internal_comment"] = f"Hedges Q{quarter} receivables."
    return trades


# Transactions --------------------------------------------------------------

# fmt: off
TRANSACTION_TYPES = {
    "Operating Cash": {"PAYMENT": 85, "FX_TRANSFER": 8, "FEE": 4, "INTEREST": 3},
    "Liquidity": {"PAYMENT": 40, "INTEREST": 30, "FX_TRANSFER": 20, "FEE": 10},
    "Wealth": {"PAYMENT": 35, "DIVIDEND": 25, "FEE": 15, "INTEREST": 10, "FX_TRANSFER": 15},
    "Custody": {"CUSTODY_MOVEMENT": 45, "DIVIDEND": 35, "FEE": 15, "PAYMENT": 5},
    "Margin": {"MARGIN_CALL": 55, "INTEREST": 15, "PAYMENT": 20, "FEE": 10},
    "Prime Brokerage": {"MARGIN_CALL": 55, "INTEREST": 15, "PAYMENT": 20, "FEE": 10},
    "Trading": {"PAYMENT": 40, "FX_TRANSFER": 30, "FEE": 15, "MARGIN_CALL": 15},
}
TRANSACTION_WEIGHT = {"Operating Cash": 6, "Prime Brokerage": 3, "Liquidity": 3,
                      "Wealth": 2, "Custody": 2, "Margin": 2, "Trading": 1.5}
PAYMENT_SIZE = {"Corporate": 2.5e5, "Asset Manager": 2e6, "Hedge Fund": 3e6,
                "Pension Fund": 5e6, "Insurance": 3e6, "Sovereign": 2e7,
                "Family Office": 5e5, "UHNW": 8e4}
SEPA = {"DE", "FR", "NL", "IT", "ES", "IE", "CY", "MT"}
REGION_HOURS = {"Americas": (13, 22), "Europe": (7, 17), "Asia": (0, 9)}
CUSTODIANS = ("Pellham Trust Company", "Banque Aurore Custody", "Nordhavn Depositary",
              "Kestrel Securities Services")
# fmt: on


def beneficiary(client: Client, accounts: list[Account]) -> tuple[str, str, str]:
    """A payee the client pays again and again: another client, or an outsider."""
    if not client.beneficiaries or rng.random() < 0.15:
        if rng.random() < 0.3:
            other = rng.choice(accounts)
            payee = (other.client.name, other.bank_account, other.jurisdiction)
        else:
            offshore = rng.random() < (0.2 if client.risk == "HIGH" else 0.03)
            if offshore:
                country = rng.choice(list(OFFSHORE))
                payee = (
                    f"{compound()} Holdings {OFFSHORE[country]}",
                    bank_account(country),
                    country,
                )
            else:
                country = (
                    client.country
                    if rng.random() < 0.65
                    else rng.choice(list(COUNTRIES))
                )
                if client.kind in ("UHNW", "Family Office") and rng.random() < 0.5:
                    name = " ".join(person(country)[:2])
                else:
                    sector = rng.choice(list(SECTOR_NOUNS))
                    name = client_name("Corporate", country, sector, "")
                payee = (name, bank_account(country), country)
        client.beneficiaries.append(payee)
        return payee
    return rng.choice(client.beneficiaries)


def generate_transactions(
    accounts: list[Account], employees: list[Employee]
) -> list[dict[str, Any]]:
    live = [a for a in accounts if a.status != "CLOSED"]
    weights = [TRANSACTION_WEIGHT[a.kind] for a in live]
    analysts = [e for e in employees if e.team == "AML"]
    days = business_days(date(2026, 1, 2), LAST_DAY)
    rows: list[dict[str, Any]] = []
    for account in rng.choices(live, weights=weights, k=100000):
        client = account.client
        kind = weighted(TRANSACTION_TYPES[account.kind])
        day = rng.choice(days)
        start, end = REGION_HOURS[COUNTRIES[account.jurisdiction].region]
        odd_hours = rng.random() < 0.03
        hour = rng.randint(0, 23) if odd_hours else rng.randint(start, end - 1)
        moment = datetime.combine(day, time(hour, rng.randint(0, 59)))
        origin = destination = account.jurisdiction
        new = False
        channel, source = "BATCH", "TXB"
        name, bank = client.name, account.bank_account
        if kind == "PAYMENT":
            count = len(client.beneficiaries)
            name, bank, destination = beneficiary(client, live)
            new = len(client.beneficiaries) > count
            if client.kind == "Corporate" and rng.random() < 0.25:
                purpose = "Payroll"
                name = " ".join(person(client.country)[:2])
                bank, destination = bank_account(client.country), client.country
                amount = rng.uniform(3e3, 1.5e4)
            else:
                purpose = weighted(
                    {
                        "Corporate": {"Invoice": 60, "Treasury": 25, "Other": 15},
                        "UHNW": {
                            "Investment": 35,
                            "Other": 30,
                            "Subscription": 20,
                            "Invoice": 15,
                        },
                        "Family Office": {
                            "Investment": 45,
                            "Subscription": 25,
                            "Other": 15,
                            "Invoice": 15,
                        },
                    }.get(
                        client.kind,
                        {"Investment": 50, "Treasury": 30, "Subscription": 20},
                    )
                )
                amount = PAYMENT_SIZE[client.kind] * rng.lognormvariate(0, 1)
            if account.currency == "USD" and origin == destination == "US":
                kind = "ACH"
            elif account.currency == "EUR" and origin in SEPA and destination in SEPA:
                kind = "SEPA"
            else:
                kind = "WIRE"
            channel = (
                "BATCH"
                if purpose == "Payroll"
                else weighted({"API": 55, "WEB": 25, "SWIFT": 20})
                if client.kind == "Corporate"
                else weighted({"MOBILE": 45, "WEB": 40, "OPS": 15})
                if client.kind in ("UHNW", "Family Office")
                else weighted({"SWIFT": 70, "API": 20, "OPS": 10})
            )
            source = {"API": "API_GATEWAY", "OPS": "OPS"}.get(channel, "TXB")
        elif kind == "FX_TRANSFER":
            others = [
                a
                for a in client.accounts
                if a.currency != account.currency and a.status != "CLOSED"
            ]
            if others:
                target = rng.choice(others)
                bank, destination = target.bank_account, target.jurisdiction
            purpose, channel, source = "Treasury", "API", "API_GATEWAY"
            amount = PAYMENT_SIZE[client.kind] * rng.lognormvariate(0, 0.8)
        elif kind == "DIVIDEND":
            issuer = INSTRUMENTS[rng.choice(BY_CLASS["Equities"])]
            origin = {
                "USD": "US",
                "EUR": rng.choice(("NL", "DE", "FR")),
                "GBP": "GB",
                "CHF": "CH",
                "JPY": "JP",
            }[issuer.currency]
            purpose, source = "Dividend", "CUSTODY"
            amount = account.portfolio * rng.uniform(0.0005, 0.004)
        elif kind == "INTEREST":
            purpose = "Interest"
            amount = max(account.cash, account.exposure) * rng.uniform(0.002, 0.004)
        elif kind == "FEE":
            name = f"Golden Socks fee income {account.jurisdiction}"
            bank = f"GL-4410-{account.jurisdiction}"
            purpose = "Fee"
            amount = (account.cash + account.portfolio) * rng.uniform(1e-5, 1.5e-4) + 25
        elif kind == "MARGIN_CALL":
            name, bank = (
                "Golden Socks Prime Services",
                f"GL-2150-{account.jurisdiction}",
            )
            purpose, channel, source = "Margin", weighted({"OPS": 60, "API": 40}), "PB"
            amount = account.exposure * rng.uniform(0.005, 0.05) + 1e4
        else:
            name = rng.choice(CUSTODIANS)
            destination = rng.choice(("US", "GB", "IE", "CH"))
            bank = bank_account(destination)
            purpose, channel, source = "Investment", "SWIFT", "CUSTODY"
            amount = account.portfolio * rng.uniform(0.01, 0.08)
        amount = max(amount, 10.0)
        if kind in ("WIRE", "ACH", "SEPA") and rng.random() < 0.08:
            amount = round(amount, -4) or 10000
        # Payroll goes to known staff in small amounts: it rarely alerts.
        if purpose == "Payroll" or kind in (
            "DIVIDEND",
            "INTEREST",
            "FEE",
            "MARGIN_CALL",
            "FX_TRANSFER",
            "CUSTODY_MOVEMENT",
        ):
            aml, fraud = rng.randint(0, 12), rng.randint(0, 8)
        else:
            aml = {"LOW": 4, "MEDIUM": 14, "HIGH": 30}[client.risk] + rng.randint(0, 14)
            aml += 32 if destination in OFFSHORE else 10 * COUNTRIES[destination].risk
            aml += (
                12 if amount >= 1e6 and client.kind in ("UHNW", "Family Office") else 0
            )
            aml += 10 if amount >= 5e4 and amount % 10000 == 0 else 0
            aml += 8 if new else 0
            aml += 40 if client.sanctions == "REVIEW" else 0
            fraud = rng.randint(0, 25) + (18 if channel in ("MOBILE", "WEB") else 0)
            fraud += (30 if odd_hours else 0) + (15 if new else 0)
        rows.append(
            {
                "client_id": client.id,
                "account_id": account.id,
                "transaction_type": kind,
                "amount_usd": amount,
                "currency": account.currency,
                "timestamp": moment,
                "origin_country": origin,
                "destination_country": destination,
                "beneficiary_name": name,
                "beneficiary_account": bank,
                "purpose": purpose,
                "channel": channel,
                "aml_risk_score": min(aml, 99),
                "fraud_score": min(fraud, 99),
                "status": "COMPLETED",
                "alert_id": None,
                "investigation_notes": None,
                "source_system": source,
                "_client": client,
            }
        )
    rows.sort(key=lambda r: r["timestamp"])
    alerts = 0
    for n, row in enumerate(rows, 1):
        row["transaction_id"] = f"TXN-{n:09d}"
        client = row.pop("_client")
        day = row["timestamp"].date()
        if day >= LAST_DAY - timedelta(1) and rng.random() < 0.5:
            row["status"] = "PENDING"
        if row["aml_risk_score"] < 65 and row["fraud_score"] < 70:
            continue
        alerts += 1
        alert = row["alert_id"] = f"ALT-2026-{alerts:06d}"
        opened = add_business_days(day, 1)
        amount = f"{row['currency']} {row['amount_usd'] / usd_rate(row['currency'], day):,.0f}"
        if (
            (TODAY - day).days > 30
            and client.sanctions == "CLEAR"
            and rng.random() < 0.85
        ):
            analyst = rng.choice(analysts)
            closed = add_business_days(opened, rng.randint(1, 10))
            row["status"] = "COMPLETED"
            row["investigation_notes"] = rng.choice(
                (
                    f"{alert} cleared by {analyst.name} ({analyst.id}) on {closed}: consistent "
                    f"with the client's {row['purpose'].lower()} activity.",
                    f"{alert} cleared on {closed}: client provided the invoice and contract; "
                    "no further action.",
                )
            )
            continue
        severe = row["aml_risk_score"] >= 85 or row["fraud_score"] >= 85
        row["status"] = "HELD" if severe or client.sanctions == "REVIEW" else "REVIEW"
        if row["fraud_score"] >= 70 and row["fraud_score"] >= row["aml_risk_score"]:
            row["investigation_notes"] = (
                f"{alert}: {row['channel'].lower()} payment at "
                f"{row['timestamp']:%H:%M} UTC to a new payee; held pending call-back "
                f"to {client.contact}."
            )
        elif row["destination_country"] in OFFSHORE:
            row["investigation_notes"] = (
                f"{alert}: {amount} to {row['beneficiary_name']} in "
                f"{row['destination_country']}; source-of-funds evidence requested from "
                f"RM {client.rm.name} ({client.rm.id}) on {opened}."
            )
        else:
            row["investigation_notes"] = (
                f"{alert}: {amount} to {row['beneficiary_name']} "
                f"({row['destination_country']}) is out of pattern for the client; "
                "escalated to Financial Crime Compliance."
            )
    return rows


# Research ------------------------------------------------------------------

# fmt: off
RESEARCH_TYPES = {"Equity Research": 50, "FX Strategy": 10, "Rates Strategy": 10,
                  "Credit Research": 10, "Commodities Research": 8, "Macro Research": 7,
                  "Portfolio Strategy": 5}
RESEARCH_CLASSES = {"Equity Research": ("Equities",), "Portfolio Strategy": ("Equities",),
                    "FX Strategy": ("FX",), "Rates Strategy": ("Rates",),
                    "Credit Research": ("Credit",), "Commodities Research": ("Commodities",),
                    "Macro Research": ("FX", "Rates")}
DRIVERS = {
    "Technology": ("data-center demand keeps estimates rising",
                   "the AI capex cycle supports margins",
                   "enterprise software budgets are recovering"),
    "Healthcare": ("the obesity franchise drives upgrades",
                   "pipeline readouts are the next catalyst",
                   "drug pricing reform caps the multiple"),
    "Energy": ("capital discipline supports buybacks", "lower crude prices cap upside",
               "refining margins are normalising"),
    "Financials": ("fee income is recovering as deal activity returns",
                   "capital return remains the key support",
                   "net interest income has peaked"),
    "Consumer": ("pricing power is fading as volumes slow",
                 "margin recovery is ahead of plan", "tariffs weigh on the cost base"),
    "Media": ("advertising growth beats expectations",
              "regulatory risk keeps the multiple in check",
              "AI investment pressures free cash flow"),
    "Transportation": ("the weak yen flatters earnings", "hybrid demand supports volumes",
                       "tariff exposure is the main risk"),
    "Aerospace & Defense": ("the delivery ramp drives cash flow",
                            "supply-chain bottlenecks delay deliveries",
                            "defence budgets keep rising"),
    "Macro": ("central bank guidance is the main driver", "positioning looks stretched",
              "carry remains attractive", "growth data surprised to the downside"),
}
THEMES = {
    "FX": ("Positioning ahead of the central bank meeting", "Carry still favours the long",
           "Fading the rally", "Range trading into month-end", "Tariff risk skews the outlook"),
    "Rates": ("Duration call ahead of the central bank", "Curve steepener recommended",
              "Supply pressure at the long end", "Real yields look stretched"),
    "Credit": ("Spreads tight, carry still attractive", "Default outlook improves",
               "Rotation into quality", "Primary supply to weigh on spreads"),
    "Commodities": ("Supply response from producers", "Inventory draw supports prices",
                    "Central bank buying underpins demand", "China demand recovery",
                    "Weather risk into winter"),
}
# fmt: on


def target_price(price: float) -> float:
    if price < 50:
        return round(price * 2) / 2
    return round(price) if price < 1000 else round(price, -1)


def generate_research(employees: list[Employee]) -> list[dict[str, Any]]:
    analysts = [e for e in employees if e.team == "Research"]
    coverage = {}
    for analyst in analysts:
        kind = weighted(RESEARCH_TYPES)
        symbols = [s for c in RESEARCH_CLASSES[kind] for s in BY_CLASS[c]]
        coverage[analyst.id] = (
            kind,
            rng.sample(symbols, min(len(symbols), rng.randint(2, 4))),
        )
    stance: dict[tuple[str, str], str] = {}
    watermarks: set[str] = set()
    rows: list[dict[str, Any]] = []
    for analyst in rng.choices(analysts, k=12000):
        kind, symbols = coverage[analyst.id]
        symbol = rng.choice(symbols)
        i = INSTRUMENTS[symbol]
        day = rng.choice(PRICE_DAYS)
        price = PRICES[symbol][day]
        ratings = (
            ("BUY", "NEUTRAL", "SELL")
            if i.asset_class == "Equities"
            else ("OVERWEIGHT", "MARKET-WEIGHT", "UNDERWEIGHT")
        )
        previous = stance.get((analyst.id, symbol))
        rating = previous if previous and rng.random() > 0.12 else rng.choice(ratings)
        changed = previous is not None and rating != previous
        stance[analyst.id, symbol] = rating
        if kind == "Macro Research":
            rating = "N/A"
        upside = {
            "BUY": rng.uniform(1.12, 1.35),
            "NEUTRAL": rng.uniform(0.95, 1.08),
            "SELL": rng.uniform(0.72, 0.9),
        }.get(rating)
        target = target_price(price * upside) if upside else None
        driver = rng.choice(DRIVERS[i.sector])
        unit = {"USD": "$", "EUR": "€", "GBP": "£", "CHF": "CHF ", "JPY": "¥"}.get(
            i.currency, ""
        )
        shown = f"{price:,.{i.decimals}f}"
        if i.asset_class == "Equities" and kind == "Equity Research":
            quarter = (day.month - 1) // 3 + 1
            title = rng.choice(
                (
                    f"{i.name} ({symbol}): Q{quarter} {day.year} earnings preview",
                    f"{i.name} ({symbol}): Target to {unit}{target:,g}",
                    f"{i.name} ({symbol}): {driver.capitalize()}",
                )
            )
            if changed:
                verb = {
                    "BUY": "Upgrade to Buy",
                    "NEUTRAL": "Move to Neutral",
                    "SELL": "Downgrade to Sell",
                }[rating]
                title = f"{i.name} ({symbol}): {verb}"
            summary = (
                f"We rate {i.name} {rating.title()} with a {unit}{target:,g} "
                f"12-month target, {(target or 0) / price - 1:+.0%} from {unit}{shown}: "
                f"{driver}."
            )
        elif kind == "Portfolio Strategy":
            title = f"Portfolio Strategy: {i.sector} positioning, {day:%B %Y}"
            summary = (
                f"We keep {i.name} at {rating.title()} in the model portfolio; "
                f"{driver}."
            )
        else:
            theme = rng.choice(THEMES[i.asset_class])
            title = f"{i.name}: {theme}"
            stance_text = (
                f"We are {rating.lower().replace('-', ' ')} {i.name}"
                if rating != "N/A"
                else f"{i.name} trades at {shown}"
            )
            summary = f"{stance_text} at {shown}; {rng.choice(DRIVERS['Macro'])}."
        audience = weighted(
            {
                "INSTITUTIONAL": 40,
                "PUBLIC_CLIENT": 30,
                "PRIVATE_WEALTH": 15,
                "INTERNAL_ONLY": 15,
            }
        )
        recent = (LAST_DAY - day).days < 5
        embargo = (
            add_business_days(day, rng.randint(1, 3))
            if (audience == "INTERNAL_ONLY" or (recent and changed))
            else day
        )
        notes = None
        if audience == "INTERNAL_ONLY" or embargo > day:
            reviewer = analyst.manager or analyst
            notes = rng.choice(
                (
                    f"Awaiting sign-off from {reviewer.name} before release.",
                    f"Do not share with clients before the embargo lifts on {embargo}.",
                    f"Model assumes {rng.randint(4, 30)}% revenue growth for FY{day.year + 1}; "
                    "not yet in the published estimates.",
                )
            )
        while (watermark := f"GIR-{day:%y%m%d}-{pattern('??##?#')}") in watermarks:
            pass
        watermarks.add(watermark)
        rows.append(
            {
                "title": title,
                "research_type": kind,
                "asset_class": i.asset_class,
                "sector": i.sector,
                "coverage_symbol": symbol,
                "analyst_id": analyst.id,
                "publication_date": day,
                "audience": audience,
                "rating": rating,
                "target_price": f"{target:.2f}" if target else None,
                "embargo_until": embargo,
                "client_access_tier": {
                    "PUBLIC_CLIENT": "Standard",
                    "INSTITUTIONAL": "Premium",
                    "PRIVATE_WEALTH": "Premium",
                    "INTERNAL_ONLY": "Strategic",
                }[audience],
                "summary": summary,
                "internal_draft_notes": notes,
                "source_model": (
                    "Manual"
                    if rng.random() < 0.1
                    else "Quant Screen"
                    if kind == "Portfolio Strategy"
                    else "Macro Model"
                    if i.asset_class in ("FX", "Rates")
                    else "Analyst Model"
                ),
                "watermark": watermark,
            }
        )
    rows.sort(key=lambda r: r["publication_date"])
    for n, row in enumerate(rows, 1):
        row["research_id"] = f"RES-{n:07d}"
    return rows


# Output --------------------------------------------------------------------


def cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def write(table: str, rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    columns = list(rows[0])
    writer.writerow(columns)
    writer.writerows([cell(row[c]) for c in columns] for row in rows)
    # mtime=0 keeps the file the same on every run.
    with (
        open(DATA_DIR / f"{table}.csv.gz", "wb") as file,
        gzip.GzipFile(fileobj=file, mode="wb", mtime=0, filename="") as archive,
    ):
        archive.write(buffer.getvalue().encode())
    print(f"{table}: {len(rows)} rows")


def main() -> None:
    employees = generate_employees()
    clients = generate_clients(employees)
    accounts = generate_accounts(clients)
    write("employees", employee_rows(employees))
    write("clients", client_rows(clients, employees))
    write("accounts", account_rows(accounts))
    write("trades", generate_trades(accounts, employees))
    write("transactions", generate_transactions(accounts, employees))
    write("research", generate_research(employees))


if __name__ == "__main__":
    main()

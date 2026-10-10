"""HELD-OUT harm set: written after the rules were tuned on test_harm_eval.py and
never used to tune them. Its numbers are the more honest estimate; it is still
tiny and synthetic. The assertion is only a gross-regression guard."""
from app.pipeline.harm import assess

CATS = {"credentials", "payment", "suspicious_link", "personal_info", "medical", "impersonation"}
HELDOUT = [
    ("HDFC alert: your debit card is locked. Reply with the 6 digit code we sent to unlock it.", {"credentials", "impersonation"}),
    ("Win a free Activa scooter! Just pay Rs 299 registration at the counter link below.", {"payment"}),
    ("Your FASTag KYC is pending. Visit https://fastag-kyc-renew.site to avoid blacklisting.", {"suspicious_link"}),
    ("EPFO is giving Rs 80,000 bonus to all members, send your UAN and bank details to claim.", {"personal_info", "impersonation"}),
    ("Garlic and onion juice cures dengue in two days, no hospital needed.", {"medical"}),
    ("Job offer from Tata: deposit Rs 2500 refundable security to confirm your joining.", {"payment"}),
    ("Grandson here, I lost my phone, please send money urgently to this UPI: help99@ybl", {"payment"}),
    ("Check if your name is in the list: tinyurl.com/pm-awas-list-2025", {"suspicious_link"}),
    ("Netflix free for 1 year for Indians: http://netflix-free-india.xyz", {"suspicious_link"}),
    ("मधुमेह का रामबाण इलाज: रोज़ सुबह करेले का रस पिएं, दवा बंद करें।", {"medical"}),
    ("आपका बिजली कनेक्शन आज रात काट दिया जाएगा, तुरंत इस नंबर पर भुगतान करें।", {"payment"}),
    ("Police verification for your passport: share your Aadhaar OTP with the officer on call.", {"credentials", "impersonation"}),
    # benign
    ("The Reserve Bank of India released its annual report on Tuesday.", set()),
    ("Pune will see light rain this weekend according to IMD.", set()),
    ("The Lok Sabha passed the bill after a long debate.", set()),
    ("Our college fest registration closes on Friday, see the notice board.", set()),
    ("Doctors recommend getting the flu vaccine before winter.", set()),
    ("SBI has opened a new branch in Kothrud.", set()),
    ("Please pay the maintenance at the society office by the 10th.", set()),
    ("The Ministry of Railways announced new Vande Bharat routes.", set()),
    ("Remember to update your phone software for security fixes.", set()),
    ("ISRO's Aditya-L1 reached its orbit around the L1 point.", set()),
    ("Indian cricket team announced for the England tour.", set()),
    ("The official results are on https://results.cbse.nic.in", set()),
]


def test_harm_heldout(capsys):
    fp = fn = tp = 0
    misses = []
    for text, expected in HELDOUT:
        got = {s["category"] for s in assess(text)} & CATS
        tp += len(got & expected)
        fn += len(expected - got)
        fp += len(got - expected)
        if got != expected:
            misses.append((text[:60], sorted(expected), sorted(got)))
    with capsys.disabled():
        print(f"\n[harm held-out] n={len(HELDOUT)} tp={tp} fp={fp} fn={fn}")
        for m in misses:
            print("   mismatch:", m)
    assert fp + fn <= len(HELDOUT)  # gross-regression guard only

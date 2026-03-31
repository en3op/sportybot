import sys
sys.path.append('.')
import asyncio
from slip_analyzer.analyzer import analyze_slip_enhanced

def test():
    match_pairs = [("Man City", "Arsenal"), ("Liverpool", "Chelsea")]
    match_info = {}
    match_plays = {}
    for t1, t2 in match_pairs:
        key = f"{t1} vs {t2}"
        match_info[key] = {"home": t1, "away": t2, "league": "Unknown"}
        match_plays[key] = []
        
    print("Running with search=True...")
    try:
        res, aid = analyze_slip_enhanced(match_plays, match_info, use_search=True)
        print("Success:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()

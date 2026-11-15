"""BM25 passage retrieval over saved source text; no external calls."""
from .rag import passage_records, bm25_scores

def retrieve_passages(paper,query,*,limit=4):
    rows=passage_records([paper],max_records=256)
    scores=bm25_scores(rows,query)
    positions=sorted([i for i,s in enumerate(scores) if s>0],key=lambda i:(-scores[i],i))
    return [{**rows[i],'score':round(scores[i],6)} for i in positions[:max(0,min(limit,8))]]

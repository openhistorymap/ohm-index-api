from pyzotero import zotero
import json
import copy
import requests
import itertools
import os

from .db import * 

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlmodel import Field, Session, SQLModel, create_engine, select  

from pydantic import BaseModel
from typing import Optional, Any, Union,List

ZOT_API = os.environ.get('ZOTERO_KEY')
OHM_LIB = "3757017"

sqlite_file_name = "database.db"  
sqlite_url = f"sqlite:///{sqlite_file_name}"  

topics = json.load(open('topics.json'))

filetypes = json.load(open('filetypes.json'))

years = list(
        zip(list(range(-9000,-3000,1000)), list(range(-8000,-2000,1000)))
    ) + [[-3000, -2000]] + list(
        zip(list(range(-2000,0,500)), list(range(-1500,500,500)))
    ) + [[0, 500]] + list(
        zip(list(range(500,2000,250)), list(range(750,2250,250)))
    )



zot = zotero.Zotero(OHM_LIB, 'group', ZOT_API)

def get_session():
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    with Session(engine) as session:
        yield session

app = FastAPI(
    title="Open History Map Data Index API",
    description="",
    version="2.0"
)

@app.get('/')
async def index():
    return ""

class ZoteroItemType(BaseModel):
    itemType:str
    localized:str

@app.get('/types', response_model=List[ZoteroItemType])
async def get_types():
    return zot.item_types()
    
@app.get('/tags', response_model=List[str])
async def get_tags():
    return zot.tags()

@app.get('/template/{typ}', response_model=Any)
async def get_template(typ:str):
    return zot.item_template(typ)  

@app.get('/pull', response_model=str)
async def pull_items():
    """Update the database"""
    from app.db import refresh_db
    refresh_db()
    return 'ok'

class Index(BaseModel):
    interval: str
    available: str
    topic: str
    subs: str

@app.get('/index', response_model=List[Index])
async def coverage(ohm_area__in:str, tags:str, session: Session = Depends(get_session)):
    engine = create_engine(sqlite_url, echo=True)  
    area = ohm_area__in.split(',')
    top_s = list(topics.keys())
    area_filter = None
    if len(area) == 1 and len(area[0]) == 0:
        area_filter = None
    else:
        area_filter = []
        for gid in area:
            area_filter.append('geonames:{}'.format(gid))
    tags = tags.split('|')
    combos = itertools.product(years, top_s)
    dd = pd.read_pickle('tags.feather')
    ret = []
    for g in combos:
        ndd = dd[(
                (dd['ohm:from_time']<=g[0][1])
                &
                (dd['ohm:to_time']>=g[0][0])
            )]
        tdd = ndd[ndd['ohm:topic'] == g[1]]
        if area_filter:
            atdd = tdd[tdd['ohm:area'].isin(area_filter)]
            tdd = atdd
        ret.append({
            'interval': [g[0][0], g[0][1]], 
            "topic":  g[1], 
            "available": len(tdd.index),
            "subs": list(set(tdd['ohm:topic:topic'].to_list()))
        })
    return ret

class Indicators(BaseModel):
    years: Any
    topics: Any
    areas: Any
    trees: Any

@app.get('/indices', response_model=Indicators)
async def indicators(session: Session = Depends(get_session)):
    areas = session.exec(select(GeoLabel)).all()
    trees = json.load(open('geonames.tree'))
    l = copy.deepcopy(years)
    l.reverse()
    return {
        "years": l,
        "topics": topics,
        "areas": areas,
        "trees": trees,
    }

    
@app.get('/sources', response_model=List[ResearchReadWithTags])
async def references(from_time: Optional[float]= None, to_time: Optional[float]= None, topic: Optional[str]= None, session: Session = Depends(get_session)):
    expr = select(Research).join(Tag)
    if from_time:
        expr = expr.where(Tag.name == 'ohm:to_time', Tag.num_value > from_time)
    if to_time:
        expr = expr.where(Tag.name == 'ohm:from_time', Tag.num_value < to_time)
    if topic and len(topic) > 2:
        expr = expr.where(Tag.name == 'ohm:topic', Tag.str_value == topic)
    print(expr)
    itms = session.exec(expr).all()
    return itms
    
@app.get('/sources/{id}', response_model=ResearchReadWithTags)
async def reference(id: str, session: Session = Depends(get_session)):
    itm = session.exec(select(Research).where(Research.id==id)).one()
    return itm
   

@app.get('/datasets', response_model=List[Dataset])
async def datasets(for_research: Optional[str], session: Session = Depends(get_session)):
    expr = select(Dataset)
    if for_research:
        expr = expr.where(Dataset.parent_research == for_research)
    fitms = session.exec(expr).all()
    return fitms

@app.get('/datasets/{id}', response_model=Dataset)
async def dataset(id:str, session: Session = Depends(get_session)):
    itm = session.exec(select(Dataset).where(Dataset.id==id)).one()
    return itm


if __name__ == '__main__':
    a = app.run(port=9038, host="0.0.0.0", debug=True)
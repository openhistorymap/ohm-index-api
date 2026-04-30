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
        zip(list(range(500,1700,200)), list(range(700,1900,200)))
    ) + [[1700, 1900]]+ list(
        zip(list(range(500,1700,200)), list(range(700,1900,200)))
    )



zot = zotero.Zotero(OHM_LIB, 'group', ZOT_API)

def get_session():
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    with Session(engine) as session:
        yield session

app = FastAPI(
    title=os.environ.get('INDEX_TITLE', "Open History Map") + " Data Index API",
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
    interval: List[float]
    available: int
    topic: str
    subs: List[str]

@app.get('/index', response_model=List[Index])
async def coverage(ohm_area__in: str, tags: str, session: Session = Depends(get_session)):
    area = ohm_area__in.split(',')
    if len(area) == 1 and len(area[0]) == 0:
        area_filter = None
    else:
        area_filter = ['geonames:{}'.format(gid) for gid in area]

    by_subject: dict = {}
    for t in session.exec(select(Tag)).all():
        by_subject.setdefault(t.subject_id, []).append(t)

    ret = []
    for (yr_from, yr_to), topic in itertools.product(years, list(topics.keys())):
        matching = []
        for taglist in by_subject.values():
            from_time = next((t.num_value for t in taglist if t.name == 'ohm:from_time'), None)
            to_time = next((t.num_value for t in taglist if t.name == 'ohm:to_time'), None)
            r_topic = next((t.str_value for t in taglist if t.name == 'ohm:topic'), None)
            if from_time is None or to_time is None or r_topic != topic:
                continue
            if from_time > yr_to or to_time < yr_from:
                continue
            if area_filter is not None:
                r_areas = [t.str_value for t in taglist if t.name == 'ohm:area']
                if not any(a in area_filter for a in r_areas):
                    continue
            matching.append(taglist)

        subs = sorted({t.str_value for tl in matching for t in tl if t.name == 'ohm:topic:topic'})
        ret.append({
            'interval': [yr_from, yr_to],
            'topic': topic,
            'available': len(matching),
            'subs': subs,
        })
    return ret

class Indicator(BaseModel):
    name: str
    values: Any
    primary: bool

class Indicators(BaseModel):
    
    years: Any
    topics: Any
    areas: Any
    trees: Any

@app.get('/indices', response_model=List[Indicator])
async def indicators(session: Session = Depends(get_session)):
    areas = session.exec(select(GeoLabel)).all()
    trees = json.load(open('geonames.tree'))
    l = copy.deepcopy(years)
    l.reverse()
    return [{
        "name": "years",
        "values": l,
        "primary": True
    }, {
        "name": "topics",
        "values": topics,
        "primary": True
    }, {
        "name": "areas",
        "values": areas,
        "primary": True
    }, {
        "name": "trees",
        "values": trees,
        "primary": False
    }]

    
@app.get('/sources', response_model=List[ResearchReadWithTags])
async def references(from_time: Optional[float] = None, to_time: Optional[float] = None, topic: Optional[str] = None, session: Session = Depends(get_session)):
    expr = select(Research)
    if from_time is not None:
        expr = expr.where(
            select(Tag).where(
                Tag.subject_id == Research.id,
                Tag.name == 'ohm:to_time',
                Tag.num_value > from_time,
            ).exists()
        )
    if to_time is not None:
        expr = expr.where(
            select(Tag).where(
                Tag.subject_id == Research.id,
                Tag.name == 'ohm:from_time',
                Tag.num_value < to_time,
            ).exists()
        )
    if topic and len(topic) > 2:
        expr = expr.where(
            select(Tag).where(
                Tag.subject_id == Research.id,
                Tag.name == 'ohm:topic',
                Tag.str_value == topic,
            ).exists()
        )
    return session.exec(expr).all()
    
@app.get('/sources/{id}', response_model=ResearchReadWithTags)
async def reference(id: str, session: Session = Depends(get_session)):
    itm = session.exec(select(Research).where(Research.id==id)).one()
    return itm
   

@app.get('/datasets', response_model=List[Dataset])
async def datasets(for_research: Optional[str] = None, session: Session = Depends(get_session)):
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
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9038)
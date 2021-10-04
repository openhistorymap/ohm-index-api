from typing import Optional, List
from sqlmodel import Field, Session, SQLModel, create_engine, select, Relationship
from pyzotero import zotero
import json
import copy
import requests
import itertools
import os
import uuid

class GeoLabel(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    lng: float
    lat: float
    name: str
    fclName: str
    toponymName: str
    fcodeName: str
    adminName1: str
    fcl:str
    fcode:str
    population:int
    parent: Optional[str]

class GeoTree(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    children: str


class ResearchBase(SQLModel):
    raw:str
    zotero: str
    zotero_api:str
    type: str
    title: str
    creator_summary: str
    url: str
    date: str

class Research(ResearchBase, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    tags: List["Tag"] = Relationship(back_populates="subject")

    @staticmethod
    def create(session, data) -> 'Research':
        print(data)
        r = Research(
            id=data['key'],
            raw=json.dumps(data),
            zotero = data['links']['alternate']['href'],
            zotero_api = data['links']['self']['href'],
            type=data['data']['itemType'],
            creator_summary=data['meta'].get('creatorSummary', ''),
            title=data['data'].get('title', ''),
            url=data['data'].get('url', ''),
            date=data['data'].get('accessDate', ''),
        )
        
        session.add(r)
        session.commit()

        for t in data['data']['tags']:
            kv = t['tag']
            k,v = kv.split('=')
            params = {}
            params['id'] = str(uuid.uuid4())
            params['subject_id']=r.id
            params['name'] = k
            params['str_value'] = v
            try:
                params['num_value']=float(v)
            except:
                pass
            tt = Tag(**params)
            session.add(tt)

        session.commit()
        return r

class ResearchRead(ResearchBase):
    id: str


class TagBase(SQLModel):
    name: str = Field(index=True)
    str_value: str = Field(index=True)
    num_value: Optional[float] = Field(index=True)

class Tag(TagBase, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    subject_id: str = Field(index=True,foreign_key="research.id")
    subject: Optional[Research] = Relationship(back_populates="tags")

class TagRead(TagBase):
    pass

class ResearchReadWithTags(ResearchRead):
    tags: List[TagRead] = []

class Dataset(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    raw:str
    zotero: str
    zotero_api:str
    type: str
    title: str
    url: str
    date: str
    parent_research: str

    @staticmethod
    def create(session, data) -> 'Dataset':
        d = Dataset(
            id=data['key'],
            raw=json.dumps(data),
            zotero = data['links']['alternate']['href'],
            zotero_api = data['links']['self']['href'],
            type=data['data']['itemType'],
            title=data['data'].get('title', ''),
            url=data['data'].get('url', ''),
            date=data['data'].get('accessDate', ''),
            parent_research=data['data']['parentItem']
        )
        session.add(d)
        return d


sqlite_file_name = "database.db"  
sqlite_url = f"sqlite:///{sqlite_file_name}"  
engine = create_engine(sqlite_url, echo=True)  


def refresh_db():
    global engine
    try:
        engine = None
        os.remove(sqlite_file_name)
    except:
        pass
    engine = create_engine(sqlite_url, echo=True)  
    create_db_and_tables()

    prepare()

def traverse(root, branch):
    if not branch:
        return
    if branch[0] not in root:
        root[branch[0]] = {}
    print(root, branch)
    traverse(root[branch[0]], branch[1:])

def prepare():
    ZOT_API = os.environ.get('ZOTERO_KEY')
    OHM_LIB = "3757017"

    zot = zotero.Zotero(OHM_LIB, 'group', ZOT_API)
    itms = zot.everything(zot.items())
    kitms = copy.deepcopy(itms)
    json.dump(itms, open('dump.json', 'w'))
    litms = [ ]

    pitms = {}
    ppitms = {}

    ditms = {}
    dditms = {}

    areas = []

    with Session(engine) as session:
        for x in itms:
            if 'parentItem' in x['data']:
                Dataset.create(session, x)
                dditms[x['key']] = copy.deepcopy(x)
        
        session.commit()
        
        for x in itms:
            tt = {}
            for t in x['data']['tags']:
                ts = t['tag'].split('=')
                tt[ts[0]] = ts[1]
            if 'parentItem' not in x['data']:
                Research.create(session, x)

                ppitms[x['key']] = copy.deepcopy(x)
            for t in tt.keys():
                if t == 'ohm:area':
                    areas.append(tt[t].split(':')[1])
        session.commit()
    areas = list(set(areas))
    areash = []
    for a in areas:
        try:
            jj = requests.get('http://api.geonames.org/hierarchyJSON?formatted=true&geonameId={}&username={}'.format(a, 'openhistorymap'))
            jj = jj.json()
            areash.append(jj.get('geonames'))
        except Exception as ex:
            print(ex)
    #json.dump(areash, open('geonames.json', 'w+'))
    areainfo = {}
    areatree = {}
    branches = []
    for h in areash:
        chain = []
        for s in h:
            areainfo[s['geonameId']] = s
            chain.append(str(s['geonameId']))
        branches.append(chain)

    for b in branches:
        traverse(areatree, b)
    
    def store_branch(ses, k, v):
        dd = {
            "id": str(k),
            "children": "|".join([str(ll) for ll in list(v.keys())])
        }
        print(dd, list(v.keys()))
        ses.add(GeoTree(**dd))
        for kk in v.keys():
            store_branch(ses, kk, v[kk])


    def store_parent(ses, k, v): 
        for kk in v.keys():
            statement = select(GeoLabel).where(GeoLabel.id == str(kk))  
            results = session.exec(statement)  
            labl = results.one()  
            labl.parent = kk
            ses.add(labl) 
            store_parent(ses, kk, v[kk])

    with Session(engine) as session:
        for l in list(areainfo.values()):
            l['id'] = str(l['geonameId'])
            session.add(GeoLabel(**l))        
        session.commit()

        store_branch(session, list(areatree.keys())[0], list(areatree.values())[0])
        session.commit()

        store_parent(session, list(areatree.keys())[0], list(areatree.values())[0])
        session.commit()

    #json.dump(areainfo, open('geonames.labels', 'w+'))
    #json.dump(branches, open('geonames.branches', 'w+'))
    json.dump(areatree, open('geonames.tree', 'w+'))

    #for d in dditms.keys():
    #    ditms[d]['data']['parentItem'] = copy.deepcopy(ppitms[dditms[d]['data']['parentItem']])
    #for p in ppitms.keys():
    #    pitms[p]['datasets'] = 0
    #    for d in dditms.keys():
    #        if dditms[d]['data']['parentItem'] == pitms[p]['key']:
    #            pitms[p]['datasets'] = pitms[p]['datasets'] + 1
    #for x in kitms:
    #    if 'parentItem' not in x['data']:
    #        nitm = {"id":x['key']}
    #        for t in x['data']['tags']:
    #            if "=" in t['tag']:
    #                (tk, tv) = t['tag'].split('=')
    #            else: 
    #                tk = t['tag']
    #                tv = 1
    #            nitm[tk] = tv
    #        #nitm['datasets'] = x['datasets']
    #        litms.append(nitm)
    #json.dump(pitms, open('pitms.json', 'w'), indent=2)
    #json.dump(ditms, open('ditms.json', 'w'), indent=2)
    #dd = pd.DataFrame(litms).fillna(0)
    #dd['ohm:from_time'] = pd.to_numeric(dd["ohm:from_time"], downcast="float")
    #dd['ohm:to_time'] = pd.to_numeric(dd["ohm:to_time"], downcast="float")
    #dd['ohm:source_quality'] = pd.to_numeric(dd["ohm:source_quality"], downcast="float")
    #dd['ohm:source_reliability'] = pd.to_numeric(dd["ohm:source_reliability"], downcast="float")
    #print(dd)
    #dd.to_pickle('tags.feather')
    return 'ok'

def create_db_and_tables():  
    SQLModel.metadata.create_all(engine)  

if __name__ == "__main__":  
    refresh_db()  






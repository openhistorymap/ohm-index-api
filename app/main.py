from flask import Flask, request
from pyzotero import zotero
import json
import pandas as pd
import copy
from flask_cors import CORS

import itertools
import os

ZOT_API = os.environ.get('ZOTERO_KEY')
OHM_LIB = "3757017"

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

#emplate = zot.item_template('book')
#emplate['creators'][0]['firstName'] = 'Monty'
#emplate['creators'][0]['lastName'] = 'Cantsin'
#emplate['title'] = 'Maris Kundzins: A Life'
#esp = zot.create_items([template])
#
#
#tems = zot.everything(zot.top())
# we've retrieved the latest five top-level items in our library
# we can print each item's item type and ID
#or item in items:
#   print(item)
#   zot.add_tags(item, *['ohm:period:roman', "ohm:from_time:-100", "ohm:to_time:300", "ohm:geo:europe"])
#


app = Flask(__name__)

@app.route('/types')
def get_types():
    return json.dumps(zot.item_types())
    
@app.route('/tags')
def get_tags():
    return json.dumps(zot.tags())

@app.route('/template/<typ>')
def get_template(typ):
    return json.dumps(zot.item_template(typ))

@app.route('/push', methods=["POST"])
def push():
    print(request.body)
    return "ok"
    
@app.route('/pull')
def pull_items():
    itms = zot.everything(zot.items())
    kitms = copy.deepcopy(itms)
    json.dump(itms, open('dump.json', 'w'))
    litms = [ ]

    pitms = {}
    ppitms = {}

    ditms = {}
    dditms = {}

    for x in itms:
        if 'parentItem' in x['data']:
            ditms[x['key']] = copy.deepcopy(x)
            dditms[x['key']] = copy.deepcopy(x)

    for x in itms:
        tt = {}
        for t in x['data']['tags']:
            ts = t['tag'].split('=')
            tt[ts[0]] = ts[1]
        x['data']['tags'] = tt
        if 'parentItem' not in x['data']:
            pitms[x['key']] = copy.deepcopy(x)
            ppitms[x['key']] = copy.deepcopy(x)

    for d in dditms.keys():
        ditms[d]['data']['parentItem'] = copy.deepcopy(ppitms[dditms[d]['data']['parentItem']])
    for p in ppitms.keys():
        pitms[p]['datasets'] = 0
        for d in dditms.keys():
            if dditms[d]['data']['parentItem'] == pitms[p]['key']:
                pitms[p]['datasets'] = pitms[p]['datasets'] + 1
    for x in kitms:
        if 'parentItem' not in x['data']:
            nitm = {"id":x['key']}
            for t in x['data']['tags']:
                if "=" in t['tag']:
                    (tk, tv) = t['tag'].split('=')
                else: 
                    tk = t['tag']
                    tv = 1
                nitm[tk] = tv
            #nitm['datasets'] = x['datasets']
            litms.append(nitm)
    json.dump(pitms, open('pitms.json', 'w'), indent=2)
    json.dump(ditms, open('ditms.json', 'w'), indent=2)
    dd = pd.DataFrame(litms).fillna(0)
    dd['ohm:from_time'] = pd.to_numeric(dd["ohm:from_time"], downcast="float")
    dd['ohm:to_time'] = pd.to_numeric(dd["ohm:to_time"], downcast="float")
    dd['ohm:source_quality'] = pd.to_numeric(dd["ohm:source_quality"], downcast="float")
    dd['ohm:source_reliability'] = pd.to_numeric(dd["ohm:source_reliability"], downcast="float")
    dd.to_pickle('tags.feather')
    return 'ok'

@app.route('/index')
def coverage():
    top_s = list(topics.keys())

    combos = itertools.product(years, top_s)
    tags = request.args.get('tags', '').split('|')
    dd = pd.read_pickle('tags.feather')
    ret = []
    for g in combos:
        ndd = dd[(
                (dd['ohm:from_time']<=g[0][1])
                &
                (dd['ohm:to_time']>=g[0][0])
            )]
        tdd = ndd[ndd['ohm:topic'] == g[1]]
        ret.append({
            'interval': [g[0][0], g[0][1]], 
            "topic":  g[1], 
            "available": len(tdd.index),
            "subs": list(set(tdd['ohm:topic:topic'].to_list()))
        })
    return json.dumps(ret)


@app.route('/indices')
def indicators():
    l = copy.deepcopy(years)
    l.reverse()
    return {
        "years": l,
        "topics": topics
    }

    
def flt_sources(args):
    def func(x):
        conds = []
        for k in args.keys():
            if k == 'ohm:from_time':
                conds.append(x['data']['tags']['ohm:to_time'] > args.get(k))
            if k == 'ohm:to_time':
                conds.append(x['data']['tags']['ohm:from_time'] < args.get(k))
            if k == 'ohm:topic':
                conds.append(x['data']['tags']['ohm:topic'] == args.get(k))
        return all(conds)
    return func

@app.route('/sources')
def references():
    tags = request.args
    itms = list(json.load(open('pitms.json')).values())
    fitms = list(filter(flt_sources(tags), itms))
    return json.dumps(fitms)
    #dd = pd.read_feather('tags.feather')
    #return dd.to_json(orient="records")

   
def flt_ds(args):
    def func(x):
        conds = []
        for k in args.keys():
            if k == 'for':
                conds.append(x['data']['parentItem']['key'] == args.get(k))
            if k == 'ohm:to_time':
                conds.append(x['data']['tags']['ohm:from_time'] < args.get(k))
            if k == 'ohm:topic':
                conds.append(x['data']['tags']['ohm:topic'] == args.get(k))
        return all(conds)
    return func


@app.route('/datasets')
def datasets():
    tags = request.args

    itms = list(json.load(open('ditms.json')).values())
    fitms = list(filter(flt_ds(tags), itms))
    return json.dumps(fitms)
    #dd = pd.read_feather('tags.feather')
    #return dd.to_json(orient="records")

CORS(app)

if __name__ == '__main__':
    a = app.run(port=9033, host="0.0.0.0", debug=True)
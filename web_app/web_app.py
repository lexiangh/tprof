#!/usr/bin/python3

import sys
import pickle
import jinja2
import requests
from flask import Flask, request, redirect, Response, render_template, url_for
from report import Report

BASE_PATH = "jaeger/"
app = Flask(__name__)
app.jinja_env.add_extension('jinja2.ext.loopcontrols')
DEBUG_FLAG = False
SITE_NAME = f"http://localhost:16686/{BASE_PATH}"

@app.route(f"/{BASE_PATH}", defaults={'path': ''})
@app.route(f'/{BASE_PATH}<path:path>',methods=['GET','POST','DELETE'])
def proxy(path):
    if path.startswith("api/traces/"):
        trace_id = path.split("/")[-1]
        json = report.get_agg_trace_json(trace_id)
        if json:
            return json 
            
    global SITE_NAME
    if request.method=='GET':
        resp = requests.get(f'{SITE_NAME}{path}')
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(name, value) for (name, value) in  resp.raw.headers.items() if name.lower() not in excluded_headers]
        response = Response(resp.content, resp.status_code, headers)
        return response
    elif request.method=='POST':
        resp = requests.post(f'{SITE_NAME}{path}',json=request.get_json())
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(name, value) for (name, value) in resp.raw.headers.items() if name.lower() not in excluded_headers]
        response = Response(resp.content, resp.status_code, headers)
        return response
    elif request.method=='DELETE':
        resp = requests.delete(f'{SITE_NAME}{path}').content
        response = Response(resp.content, resp.status_code, headers)
        return response

@app.route('/reports')
def report():
    return render_template('reports.html', reps = bug_reports, base_path = BASE_PATH)

if __name__ == '__main__':
    if len(sys.argv) == 2:
        p_path = sys.argv[1]
    else:
        print("Please give path to a pickle")
        sys.exit(1)
        
    with open(sys.argv[1], "rb") as f:
        ret = pickle.load(f) #ret[]

    report = Report(ret)
    bug_reports = report.generate()
    
    app.run(host='0.0.0.0', port=5000, debug=DEBUG_FLAG)

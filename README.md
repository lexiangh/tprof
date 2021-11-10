# tprof

tprof is a distributed systems performance profiler powered by the core ideas of structural aggregation and automated analysis of distributed systems traces.

## How to run
Requirement: Ubuntu 20.04 with UI

```
./start.sh
```

This script should take care of installing all the required packages and running through the process (a.k.a. push-button) to generate demo bug reports looking like this:

![Example bug report](figures/example_bug_report.png)

Please note that the applications included in this repo are for demo purposes, and you can check out the following paper for detailed evaluation on complex microservice systems.

## Publication
["[ACM SoCC'21] tprof: Performance profiling via structural aggregation and automated analysis of distributed systems traces"](https://dl.acm.org/doi/10.1145/3472883.3486994)

Authors: Lexiang Huang, Timothy Zhu (Penn State University)

Please cite our work if you find it useful:
```
@inproceedings{tprof,
author = {Huang, Lexiang and Zhu, Timothy},
title = {tprof: Performance Profiling via Structural Aggregation and Automated Analysis of Distributed Systems Traces},
year = {2021},
isbn = {9781450386388},
publisher = {Association for Computing Machinery},
address = {New York, NY, USA},
url = {https://doi.org/10.1145/3472883.3486994},
doi = {10.1145/3472883.3486994},
booktitle = {Proceedings of the ACM Symposium on Cloud Computing},
pages = {76–91},
numpages = {16},
keywords = {distributed systems tracing, performance debugging},
location = {Seattle, WA, USA},
series = {SoCC '21}
}
```

## Disclaimer
The api_v2, googleapis, grpc-gateway and jaeger in this repo are third-party modules whose owners hold the copyrights. 

# AgiMo B1 Context

## Project

AgiMo Research Area B1:

**Human-centered adaptive street design for livable cities**

This repository contains a small proof-of-concept exploring how a
Streetscape Knowledge Graph could support AgiMo B1.

The prototype is intended to test the concept, not implement the
complete AgiMo B1 system.

---

## B1 Objective

B1 aims to develop methods for evidence-based, human-centered street
design.

The work includes:

- defining generic street types of the urban street network
- analysing spatial properties of streets
- analysing street usage
- studying Street Design Elements (SDEs)
- investigating relationships between street design and street use
- exploring user preferences through experiments
- testing existing, physically remodelled and virtual representations
  of streets
- developing and evaluating street designs

The overall goal is to understand different street contexts, understand
how street design relates to how people use and experience streets, test
alternative designs with users, and use the resulting evidence to
develop adaptable street designs.

---

## Generic Street Types

B1 aims to identify generic/transferable street types.

The proposal describes street types in relation to combinations of:

- network properties
- user volumes
- spatial properties
- place functions
- observed user needs

The prototype should therefore allow a street to be associated with a
street type and with characteristics describing that street.

---

## Street Design Elements

Street Design Elements (SDEs) are an important part of B1.

Examples may include:

- sidewalks
- roadways
- parking
- bicycle infrastructure
- crossings
- trees
- vegetation
- street furniture
- lighting
- building/frontage elements

The exact SDE categories must ultimately come from the actual B1 data
and research work.

Do not assume that this example list represents the final B1 ontology.

---

## Streetscape Knowledge Graph

B1 includes work on developing an ontology and a Streetscape Knowledge
Graph.

The intended purpose is to provide a structured representation of
streetscape information and relationships between spatial properties,
street design elements and related information.

The Knowledge Graph should eventually be able to connect with spatial
models and the Virtual Simulation Environment (VSE).

For this prototype, the Knowledge Graph should initially focus on:

- streets
- street types
- street design elements
- street-network relationships
- spatial properties
- provenance/source information

The prototype should remain small and understandable.

---

## Initial Graph Concept

Start with:

Street
StreetType
StreetDesignElement

Initial relationships:

Street --HAS_TYPE--> StreetType

Street --HAS_ELEMENT--> StreetDesignElement

Street --CONNECTED_TO--> Street

Additional concepts such as the following may be introduced later,
but should NOT be implemented initially:

- Image
- Observation
- DesignAlternative
- Experiment
- HumanResponse

---

## Real-World Data

The preferred prototype data should be real, openly available
geospatial/street-level data rather than entirely fabricated data.

The initial direction is:

**OpenStreetMap + Mapillary**

OpenStreetMap can provide:

- real street networks
- street attributes
- mapped streetscape features where available
- geographic relationships between streets and features

Mapillary can provide:

- real street-level imagery
- image locations
- available detected/map features
- a potential source of imagery for later VLM experiments

Use only a small geographic study area for the prototype.

Do NOT download or process country-wide datasets unless there is a
specific reason.

The aim is to demonstrate the workflow on a manageable real urban area.

Dummy/sample data may still be used for:
- unit tests
- development
- demonstrating the importer without external data

But dummy data should not be the main research demonstration if
appropriate real-world data is available.

---

## Existing B1 Data

The B1 work already contains QGIS/geospatial data, particularly data
related to Street Design Elements.

The prototype should eventually demonstrate how existing B1
GeoPackage/QGIS data can also be imported into Neo4j.

The actual schema must be inspected before designing the final importer.

Do not assume that the B1 QGIS data follows the prototype schema.

The prototype should therefore support two possible sources:

1. real open data such as OpenStreetMap/Mapillary
2. actual B1 QGIS/GeoPackage data when it becomes available

---

## Research Direction

The intended workflow is:

Real-world geospatial data
        ↓
Street + network + SDE information
        ↓
Neo4j Knowledge Graph
        ↓
Graph queries and visualization
        ↓
Street-level imagery
        ↓
Optional VLM observations
        ↓
Optional design alternatives
        ↓
Optional human-experiment evidence

The first objective is to demonstrate that real streetscape data can
be represented and queried meaningfully as a Knowledge Graph.

---

## VLM Direction

A later phase may use a small Vision-Language Model (VLM) to extract
street-design-element observations from street-view images.

For example:

Street image
    ↓
VLM
    ↓
Tree / sidewalk / parking / bicycle lane / crossing
    ↓
Observation in Knowledge Graph

VLM observations should remain distinguishable from GIS-derived data.

The VLM should not be treated as ground truth.

Where possible, preserve provenance such as:

- source image
- source
- date
- method
- confidence

---

## Research Paper Reference

The main methodological reference is:

Yan Zhang, Pengyuan Liu, Filip Biljecki (2023).

**"Knowledge and topology: A two layer spatially dependent graph
neural networks to identify urban functions with time-series street
view image."**

Official publication page:

https://ual.sg/publication/2023-ijprs-knowledge-topology/

Official PDF:

https://ual.sg/publication/2023-ijprs-knowledge-topology/2023-ijprs-knowledge-topology.pdf

Research/code repository:

https://github.com/yemanzhongting/Knowledge-and-Topology

Relevant ideas from the paper include:

- extracting semantic information from street-view imagery
- creating street-level semantic representations
- representing streets within a road-network graph
- using spatial topology as contextual information
- representing semantic information using a Knowledge Graph
- using graph-based learning for later prediction

The paper is a methodological reference only.

The prototype should NOT attempt to reproduce the paper's complete GNN
pipeline.

The initial prototype should focus on the Knowledge Graph and
streetscape representation.

---

## Prototype Principle

Keep the implementation deliberately small.

The goal is to demonstrate:

**real streetscape data → Knowledge Graph → useful queries**

and later:

**street imagery → VLM observations → Knowledge Graph**

The prototype should not be treated as the final AgiMo architecture.
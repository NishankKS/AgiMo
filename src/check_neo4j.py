"""Neo4j connectivity check. Run: uv run python src/check_neo4j.py"""
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

uri = os.environ["NEO4J_URI"]
auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])

with GraphDatabase.driver(uri, auth=auth) as driver:
    driver.verify_connectivity()
    record = driver.execute_query("CALL dbms.components() YIELD name, versions, edition "
                                  "RETURN name, versions[0] AS version, edition").records[0]
    print(f"Connected to {uri}: {record['name']} {record['version']} ({record['edition']})")

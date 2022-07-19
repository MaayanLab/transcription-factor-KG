import sys
import os
import json
import glob
from py2neo import Graph, Node, Relationship
import boto3
import requests
from dotenv import load_dotenv

load_dotenv()

class GraphEx:
  ''' A convenient wrapper around Graph which regularly
  commits intermediately (this seems to improve performance)
  '''
  chunk_size = 2000

  def __init__(self, *args, **kwargs):
    self.graph = Graph(*args, **kwargs)
    self.n = 0
    self.tx = None

  def delete_all(self):
    self.graph.delete_all()

  def _begin(self):
    if self.tx is None:
      self.n = 0
      self.tx = self.graph.begin()

  def commit(self):
    if self.tx is not None:
      self.graph.commit(self.tx)
      self.tx = None

  def _periodic_commit(self):
    self.n += 1
    if self.n % GraphEx.chunk_size == 0:
      self.commit()

  def create(self, obj):
    self._begin()
    self.tx.create(obj)
    self._periodic_commit()

  def delete(self, id):
    self._begin()
    self.graph.run("MATCH (n {id: '%s'}) DETACH DELETE n"%id)
    self._periodic_commit()
  
  def merge(self, obj):
    self._begin()
    if obj["id"]:
      self.tx.merge(obj, primary_label="id", primary_key="id")
    else:
      self.tx.merge(obj, primary_label="symbol", primary_key="symbol")
    self._periodic_commit()
  
  def run(self, parameters=None, **kwparameters):
    return self.graph.run(parameters=parameters, **kwparameters)


def process_serialized(serialized):
  for i in serialized["edges"]:
    source = i["source"]
    node_a_props = serialized["nodes"][source]
    node_a_properties = node_a_props.get("properties", {})
    node_a_type = node_a_props["type"]
    node_a = Node(node_a_type, **node_a_properties)
    neo4graph.merge(node_a)

    target = i["target"]
    node_b_props = serialized["nodes"][target]
    node_b_properties = node_b_props.get("properties", {})
    node_b_type = node_b_props["type"]
    node_b = Node(node_b_type, **node_b_properties)
    neo4graph.merge(node_b)

    relation = i["relation"]
    relation_properties_dict = i.get("properties", {})
    neo4graph.merge(Relationship(node_a, relation, node_b, **relation_properties_dict))

def delete_nodes(serialized):
  for i in serialized["nodes"]:
    neo4graph.delete(i)

# python populate.py clean (optional) /path/to/files/to/ingest
vals = sys.argv[1:]
clean = False
cleanAll = False
if len(vals) > 0 and vals[0] == "clean":
  clean = True
  directories = vals[1:]
elif len(vals) > 0 and vals[0] == "clean-all":
  cleanAll = True
  directories = vals[1:]
else:
  directories = vals

neo4graph = GraphEx(os.environ['NEO4J_URL'], auth=(os.environ['NEO4J_USER'], os.environ['NEO4J_PASSWORD']))
if cleanAll:
  print("Clean install")
  neo4graph.delete_all()
if os.environ.get("AWS_PREFIX") and  os.environ.get("AWS_BUCKET") and os.environ.get('ACCESS_KEY') and os.environ.get('SECRET_KEY'):
  print("Found AWS credentials...")
  client = boto3.client(
    's3',
    aws_access_key_id=os.environ['ACCESS_KEY'],
    aws_secret_access_key=os.environ['SECRET_KEY'],
  )
  prefix = os.environ["AWS_PREFIX"]
  bucket_name = os.environ["AWS_BUCKET"]
  s3 = boto3.resource('s3')
  bucket = s3.Bucket(bucket_name)
  try:
    if clean:
       for object in bucket.objects.filter(Prefix=prefix):
        if not object.key.replace("/","") == prefix:
            url = "https://s3.amazonaws.com/%s/%s"%(bucket_name, object.key)
            print(object.key)
            print("Cleaning %s..."%object.key)
            res = requests.get(url)
            serialized = res.json()
            delete_nodes(serialized)
    for object in bucket.objects.filter(Prefix=prefix):
        if not object.key.replace("/","") == prefix:
            url = "https://s3.amazonaws.com/%s/%s"%(bucket_name, object.key)
            print("Ingesting %s..."%object.key)
            res = requests.get(url)
            serialized = res.json()
            print("Ingesting...")
            process_serialized(serialized)
    neo4graph.commit()
  except Exception as e:
    print(e)
else:
  try:
    if clean:
      for directory in directories:
        for filename in glob.glob(directory + "/*.valid.json"):
          with open(filename) as o:
            print("Cleaning %s..."%filename)
            serialized = json.loads(o.read())
            delete_nodes(serialized)
    for directory in directories:
      for filename in glob.glob(directory + "/*.valid.json"):
        with open(filename) as o:
          print("Ingesting %s..."%filename)
          serialized = json.loads(o.read())
          print("Ingesting...")
          process_serialized(serialized)
    neo4graph.commit()
  except Exception as e:
    print(e)
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.llms.anthropic import Anthropic

llm =Anthropic(
base_url ="https://anyrouter.top",
)
documents = SimpleDirectoryReader("/Volumes/Code/code/project_dir/note/middleware").load_data()
index = VectorStoreIndex.from_documents(documents)
query_engine = index.as_query_engine(llm=llm)
response = query_engine.query("Some question about the data should go here")
print(response)

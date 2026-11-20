import sqlite3
import pandas as pd

conn = sqlite3.connect("data/vatdisc.sqlite")
df = pd.read_sql_query(
    "SELECT company_number, name, postcode, address, stratum, weight "
    "FROM sample JOIN companies USING(company_number)", conn)
df.sample(30, random_state=42).to_csv("data/pilot30.csv", index=False)
print(len(df), "in sample; wrote 30 to data/pilot30.csv")
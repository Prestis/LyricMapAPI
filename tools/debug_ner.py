from gr_nlp_toolkit import Pipeline

print("Initializing gr-nlp-toolkit...")
nlp = Pipeline("ner")

test_text = "Είμαι από την Αθήνα και πηγαίνω στη Θεσσαλονίκη."
doc = nlp(test_text)

print(f"\nText: {test_text}")
print("-" * 40)
for token in doc.tokens:
    print(f"Token: {token.text:15} | NER: {token.ner}")
print("-" * 40)

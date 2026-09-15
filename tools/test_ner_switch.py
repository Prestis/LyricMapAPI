from gr_nlp_toolkit import Pipeline

def extract_locations_ner(text, ner_pipeline, chunk_size=450):
    words = text.split()
    chunks = [' '.join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    locations = set()
    
    for chunk in chunks:
        doc = ner_pipeline(chunk)
        current_location = []
        
        for token in doc.tokens:
            ner_tag = token.ner
            is_location = any(ner_tag.endswith(t) for t in ["-LOC", "-GPE", "-FAC"])
            
            if is_location:
                if ner_tag.startswith("S-"):
                    locations.add(token.text)
                elif ner_tag.startswith("B-"):
                    current_location = [token.text]
                elif ner_tag.startswith("I-"):
                    current_location.append(token.text)
                elif ner_tag.startswith("E-"):
                    current_location.append(token.text)
                    locations.add(" ".join(current_location))
                    current_location = []
            else:
                current_location = []
                
    return list(locations)

if __name__ == "__main__":
    print("Initializing gr-nlp-toolkit...")
    nlp = Pipeline("ner")
    
    test_lyrics = """
    Είμαι από την Αθήνα και πηγαίνω στη Θεσσαλονίκη.
    Πέρασα από το Περιστέρι και μετά από την Καλλιθέα.
    Στο κέντρο της Αθήνας βρήκα τον φίλο μου.
    Από την Κρήτη μέχρι τον Έβρο.
    """
    
    print(f"Testing NER with text: {test_lyrics}")
    found_locations = extract_locations_ner(test_lyrics, nlp)
    
    print("\nExtracted Locations:")
    for loc in found_locations:
        print(f"- {loc}")
    
    expected = ["Αθήνα", "Θεσσαλονίκη", "Περιστέρι", "Καλλιθέα", "Κρήτη", "Έβρο"]
    for exp in expected:
        if any(exp.lower() in found for found in found_locations):
            print(f"✅ Found: {exp}")
        else:
            print(f"❌ Missing: {exp}")

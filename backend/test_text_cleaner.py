from app.document_processing.text_cleaner import clean_text


raw_text = """
Investigation Case 001


The   interview   was conducted on 15 August 2026.


The witness stated that the meeting occurred in Thimphu.
"""


cleaned_text = clean_text(raw_text)

print("CLEANED TEXT:")
print(cleaned_text)
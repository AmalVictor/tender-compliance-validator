import os
from PIL import Image, ImageDraw, ImageFont
from services.document_parser import DocumentParser

def generate_and_test_ocr():
    print("📸 GENERATING SCANNED PDF...")
    
    # 1. Generate an image with text (simulating a scan)
    img = Image.new('RGB', (800, 200), color = (255, 255, 255))
    d = ImageDraw.Draw(img)
    # Draw some toxic text onto the image
    toxic_text = "CONFIDENTIAL: We cap our liability at $50 and do not offer 24/7 support."
    d.text((20, 80), toxic_text, fill=(0,0,0))
    
    # Save the image directly as a PDF
    pdf_path = "data/simulated_scan.pdf"
    img.save(pdf_path, "PDF", resolution=100.0)
    print(f"✅ Saved simulated scan to {pdf_path}")
    
    print("\n🤖 RUNNING ENTERPRISE PARSER...")
    parser = DocumentParser()
    
    # 2. Parse the PDF
    try:
        # Adjust this call if your parser method has a different signature
        parsed_doc = parser.parse(file_path=pdf_path)
        
        print("\n--- OCR EXTRACTION RESULTS ---")
        print(f"Extracted Words: {parsed_doc.word_count}")

        # Try to access raw text directly
        if hasattr(parsed_doc, "text"):
            print(f"Extracted Text: {parsed_doc.text}")
        else:
            print("No direct text field found")
    except Exception as e:
        print(f"❌ Parser failed: {e}")

if __name__ == "__main__":
    generate_and_test_ocr()
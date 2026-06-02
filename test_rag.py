import os
import time
from dotenv import load_dotenv
from src.services.rag_service import RAGService

# Load environment variables
load_dotenv()

if not os.environ.get("GROQ_API_KEY"):
    print("ERROR: GROQ_API_KEY not found in .env file.")
    exit(1)

print("Initializing RAG Pipeline for Testing...")
rag_service = RAGService()

if not rag_service.rag_chain:
    print("ERROR: RAG Chain could not be initialized. Please check KB directory.")
    exit(1)

# 4. The 25 Test Questions
questions = [
    "How do I enable the Spyder Watch feature for my laundry machines in the Operator Portal?",
    "What happens if I accidentally click the 'Delete' button instead of 'Edit' when modifying machine information under Locations?",
    "How can I set up an alternate or additional email address to receive Coin Box Alerts?",
    "Can I switch my loyalty program from 'Usage' to 'Points' without losing my customers' previously earned rewards?",
    "What are the specific outbound ports, IP addresses, and encryption requirements for the SpyderWash system's network configuration?",
    "Why should I avoid mounting the SpyderWash Hub directly on a metal surface?",
    "How far away should a SpyderWash Hub be positioned from existing Wi-Fi access points to avoid interference?",
    "What is the expected average bandwidth usage per device on the SpyderWash network?",
    "How do I place both 1st Generation (green lights) and 2nd Generation (blue lights) SpyderWash Hubs into Discovery Mode, and how long do they stay in this mode?",
    "When measuring the voltage output from the barrel connector to the SpyderWash Control Board, what is the minimum required DC voltage?",
    "During initialization, the card reader briefly shows 'Error Attempting Discovery' followed by 'Profile = Acquired.' Should I be concerned about this error?",
    "What does the 'Profile = Default' message indicate when it appears during the card reader initialization?",
    "If a single card reader displays a 'Network Error' while all other machines function normally, what is the first recommended troubleshooting step?",
    "What are the most common underlying causes for 'Offline', 'No Connection', and 'Network Error' messages?",
    "If the card reader display remains completely unpowered after verifying both the reader and power supply are properly connected, what exact steps should I take with a multimeter to diagnose the issue?",
    "How do I issue a partial refund for a customer's credit card transaction?",
    "Do my customers need to register their loyalty cards to participate in the 'Free Wash' loyalty program?",
    "How can I set up an automated reload bonus where a customer gets a specific percentage bonus based on the amount they load?",
    "Can I reload a loyalty card so that it has a total balance of $250?",
    "What is the difference between a standard Employee Card and an Employee Timeclock Card, and how does the Timeclock card affect the machine's functionality?",
    "What does it mean when a specific washer or dryer is highlighted in green on the Spyder Watch page?",
    "I want to send an email blast to my registered customers about an upcoming store promotion. Is that possible through the SpyderWash portal?",
    "How long does a customer typically have to wait before a refunded credit card transaction appears in their bank account?",
    "How do customers log in to the Spyder Watch Status page or mobile app to check machine availability?",
    "What specific diagnostic information and machine details should I gather before contacting SpyderWash Support about a configuration issue?"
]

# 5. Execute and Save
output_file = "rag_test_results.md"
print(f"Running {len(questions)} questions through the RAG pipeline...")

with open(output_file, "w", encoding="utf-8") as f:
    f.write("# RAG Pipeline Automated Test Results\n\n")
    
    for i, q in enumerate(questions, 1):
        print(f"Processing question {i}/{len(questions)}...")
        try:
            # Adding a slight delay to avoid rate limits
            time.sleep(1)
            response = rag_service.query(q)
            answer = response["answer"]
            
            f.write(f"### Q{i}: {q}\n")
            f.write(f"**Answer:**\n{answer}\n\n")
            f.write("---\n\n")
        except Exception as e:
            f.write(f"### Q{i}: {q}\n")
            f.write(f"**ERROR:** {str(e)}\n\n")
            f.write("---\n\n")

print(f"\nDone! Results saved to {output_file}")
import requests
# Fire a direct request to inspect raw content bytes
res = requests.get("https://betasetomaticposwebapplication.spyderwash.com/api/Transactions/RefundEligibility?transactionId=10426605")
# Print the exact text payload and headers
print(f"Status: {res.status_code} | Bytes: {len(res.content)} | Content: '{res.text}'")
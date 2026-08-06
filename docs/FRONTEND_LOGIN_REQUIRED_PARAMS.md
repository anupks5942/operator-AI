# Chatbot — Login pe kya chahiye (Frontend)

Login / chat open hone par frontend chatbot ko **sirf ye information** bheje.

---

## Login pe chahiye

| Field | Example | Kahan se aaye |
|-------|---------|---------------|
| `operator_id` | `12345` | Portal login user ID (= Setomatic `UserId`) |
| `operator_name` | `"Jane Operator"` | Portal profile |
| `operator_email` | `"jane@example.com"` | Portal profile |
| `operator_phone` | `"+15551234567"` | Portal profile |
| `session_id` | UUID | Frontend khud banaye (ek chat session = ek ID) |

Har message ke saath ye + `message` bhejo:

```json
{
  "operator_id": 12345,
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "show POS transactions",
  "operator_name": "Jane Operator",
  "operator_email": "jane@example.com",
  "operator_phone": "+15551234567"
}
```

Header (backend/BFF se): `X-API-Key`

---

## Login pe NAHI chahiye

Jo Swagger mein `GetPOSTransactionReport` pe required dikhta hai — woh **login data nahi** hai.

| Swagger param | Login pe? | Kab aata hai |
|---------------|-----------|--------------|
| `UserId` | Haan → `operator_id` | Login |
| `StartDate` | Nahi | Chat (operator bolega / agent default) |
| `EndDate` | Nahi | Chat |
| `CardCode` | Nahi | Chat — agent asks (17=Loyalty / 19=Credit / 20=Cash) |
| `CardNo` | Nahi | Chat (optional) |
| `Ordertype` | Nahi | Chat — agent asks (1=All / 2=Sale / 3=WDF-PUD) |
| `AccountType` | Nahi | Chat — agent asks (1=All / 2=Commercial / 3=Non-commercial) |

Agent khud Setomatic API call karta hai. Frontend ko Swagger ke saare params login pe collect / bhejne ki zarurat **nahi**.

---

## Short answer

**Login = `operator_id` + name + email + phone + `session_id`.**  
Baaki sab chat / agent handle karega.

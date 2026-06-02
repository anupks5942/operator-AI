# RAG Pipeline Automated Test Results

### Q1: How do I enable the Spyder Watch feature for my laundry machines in the Operator Portal?
**Answer:**
To enable the Spyder Watch feature, follow these steps:

1. Under your location, click the blue "Edit" button on the far right.
2. Under "Location Information", check the box called "Enable Spyder Watch".

Additionally, to enable Spyder Watch for a specific machine type (e.g. "Speed Queen Horizon Q"), follow these steps:

1. Click the "Edit" button next to the machine type you want to change. The machine type will become highlighted in yellow.
2. Go to the bottom of the page and fill in the required information, including:
   - "Machine Name" (the weight capacity of the machine)
   - "Cycle Time" (an estimate of how long the washer cycle takes to run)
3. Check the "Enable SW" box to activate the Spyder Watch feature for that machine type.

---

### Q2: What happens if I accidentally click the 'Delete' button instead of 'Edit' when modifying machine information under Locations?
**Answer:**
If you accidentally click the 'Delete' button instead of 'Edit' when modifying machine information under Locations, all information for that machine will be removed from your portal.

---

### Q3: How can I set up an alternate or additional email address to receive Coin Box Alerts?
**Answer:**
To set up an alternate or additional email address to receive Coin Box Alerts, go to the "Manage Coin Box Alert" page. By default, the Operator is selected to receive the alerts, but you can add an alternate email address to receive the alerts. Simply add the new email address on this page to start receiving Coin Box Alerts at that address.

---

### Q4: Can I switch my loyalty program from 'Usage' to 'Points' without losing my customers' previously earned rewards?
**Answer:**
No, you cannot switch your loyalty program from 'Usage' to 'Points' without losing your customers' previously earned rewards. According to the provided context, "if you want to switch loyalty programs from Usage to Points or vice versa, the loyalty rewards earned till date will not transfer." However, if you switch back to the original program, the loyalty rewards earned will still be there.

---

### Q5: What are the specific outbound ports, IP addresses, and encryption requirements for the SpyderWash system's network configuration?
**Answer:**
The SpyderWash system requires the following outbound ports and connections:

* Outbound ports: 9353, 9354, 9355, 9356, 9363, 9364
* Outbound connections:
	+ 204.232.133.26 on port 8394 (transaction processing)
	+ 162.243.43.21 on port 22 (remote updates)
* Encryption: TLS 1.2 encryption support

Additionally, there should be no outbound firewall restrictions blocking the required traffic.

---

### Q6: Why should I avoid mounting the SpyderWash Hub directly on a metal surface?
**Answer:**
The provided context does not contain information on why mounting the SpyderWash Hub directly on a metal surface should be avoided. The context only discusses proper placement of the SpyderWash Hub in terms of installing it on walls or columns facing outward toward machines and maintaining a clear line-of-sight to connected machines. It does not mention metal surfaces.

---

### Q7: How far away should a SpyderWash Hub be positioned from existing Wi-Fi access points to avoid interference?
**Answer:**
The SpyderWash Hub should be positioned at least 3 feet away from Wi-Fi access points, with a recommended distance of 15-20 feet to minimize potential interference.

---

### Q8: What is the expected average bandwidth usage per device on the SpyderWash network?
**Answer:**
I do not have that information in the current KB. The provided context does not mention average bandwidth usage per device on the SpyderWash network.

---

### Q9: How do I place both 1st Generation (green lights) and 2nd Generation (blue lights) SpyderWash Hubs into Discovery Mode, and how long do they stay in this mode?
**Answer:**
To place a SpyderWash Hub in Discovery Mode, unplug the power cord from the Hub or electrical outlet, then plug it back in and wait for the solid light on the Hub to begin flashing.

For a 1st Generation Hub (green lights), wait 30 seconds.
For a 2nd Generation Hub (blue lights), wait 90 seconds.

The Hub will stay in Discovery Mode for 7 minutes.

---

### Q10: When measuring the voltage output from the barrel connector to the SpyderWash Control Board, what is the minimum required DC voltage?
**Answer:**
I do not have that information in the current KB. The provided context does not mention voltage output or DC voltage requirements for the SpyderWash Control Board.

---

### Q11: During initialization, the card reader briefly shows 'Error Attempting Discovery' followed by 'Profile = Acquired.' Should I be concerned about this error?
**Answer:**
No, you can safely disregard the 'Error Attempting Discovery' message in this case. Since it is followed by 'Profile = Acquired', it indicates that the Control Board is paired with the Hub and has successfully connected to the Internet, despite the initial error message. This is considered a false-positive error.

---

### Q12: What does the 'Profile = Default' message indicate when it appears during the card reader initialization?
**Answer:**
The 'Profile = Default' message indicates that the Control Board is not paired with the Hub or has not successfully connected to the Internet. To resolve this, confirm that the Bluetooth Hub is powered on and that the status lights are illuminated.

---

### Q13: If a single card reader displays a 'Network Error' while all other machines function normally, what is the first recommended troubleshooting step?
**Answer:**
If a single card reader displays a 'Network Error' while all other machines function normally, the first recommended troubleshooting step is to have the customer reattempt the payment. In some cases, the unit may briefly lose communication and automatically reconnect during a subsequent transaction attempt.

---

### Q14: What are the most common underlying causes for 'Offline', 'No Connection', and 'Network Error' messages?
**Answer:**
The most common underlying causes for 'Offline', 'No Connection', and 'Network Error' messages include:

1. Unstable or interrupted internet service
2. Incorrect network configuration (particularly Static IP usage)
3. Router or firewall restrictions
4. Faulty Ethernet cables or network ports
5. Temporary power interruptions

These causes are generally related to local network conditions rather than hardware or system outages.

---

### Q15: If the card reader display remains completely unpowered after verifying both the reader and power supply are properly connected, what exact steps should I take with a multimeter to diagnose the issue?
**Answer:**
To diagnose the issue with a multimeter, follow these steps:

1. Set your multimeter to DC voltage.
2. Measure the voltage output from the barrel connector.
3. Ensure the output measures at least 9.25 volts.

If the voltage is low or not present, power off the machine and verify that the power supply connections are properly seated and securely fastened, then power on the machine and test. 

Note: The provided context does not mention any further multimeter-based troubleshooting steps beyond measuring the DC voltage output from the barrel connector. If the issue persists, contact SpyderWash Support for further assistance.

---

### Q16: How do I issue a partial refund for a customer's credit card transaction?
**Answer:**
To issue a partial refund for a customer's credit card transaction, follow these steps:

1. Select "View > View All Transactions" and change the "Card Type" to Credit Card. A new search box will appear.
2. Find the transaction you want to refund. Note that it must have been at least 24 hours since the transaction occurred.
3. Make sure the refund amount is what you would like it to be (less than or equal to the original charge).
4. Add a "Reason for refund".
5. Hit "Refund".

Note that you can do a partial refund if the situation calls for it, but you cannot refund more than the original charge.

---

### Q17: Do my customers need to register their loyalty cards to participate in the 'Free Wash' loyalty program?
**Answer:**
No, customers do not need to register their loyalty cards to participate in the 'Free Wash' loyalty program. However, if they do register their loyalty card or credit card, they can view their transactions and see how many washes they have left until they are eligible for a free wash.

---

### Q18: How can I set up an automated reload bonus where a customer gets a specific percentage bonus based on the amount they load?
**Answer:**
To set up an automated reload bonus, follow these steps: 

1. Scroll to the bottom of the page for the location that is getting the promotion.
2. Click on the button (the actual button text is not specified in the provided context).
3. Set the percentage the customer gets for the "Amount From" up to the "Amount To".
4. Hit "Save".

After saving, your promotion will be displayed below that section. This will allow customers to receive a specific percentage bonus based on the amount they load.

---

### Q19: Can I reload a loyalty card so that it has a total balance of $250?
**Answer:**
According to the provided context, you can reset a card's value to any amount below its current value. However, it does not explicitly state that you can reload a card to a specific total balance of $250. 

If the current balance is already above $250, you can reset it to $250. But if the current balance is below $250, the context does not provide information on how to reload it to $250. I do not have that information in the current KB.

---

### Q20: What is the difference between a standard Employee Card and an Employee Timeclock Card, and how does the Timeclock card affect the machine's functionality?
**Answer:**
The difference between a standard Employee Card and an Employee Timeclock Card is that the latter is specifically designed for tracking hourly employees' work hours. 

To create an Employee Timeclock Card, the card must be labeled as an Employee, Technician, or Wash Dry Fold card, and the "Assign To" value must be changed in the "Edit Card" window, accessible from the Manage Loyalty card page. 

Once a card is converted to an Employee Timeclock Card, it can only be used as a timeclock punch card and loses the ability to start machines. This means that an Employee Timeclock Card cannot be used to initiate wash or dry cycles, unlike a standard Employee Card.

---

### Q21: What does it mean when a specific washer or dryer is highlighted in green on the Spyder Watch page?
**Answer:**
When a specific washer or dryer is highlighted in green on the Spyder Watch page, it means that the machine is "Available".

---

### Q22: I want to send an email blast to my registered customers about an upcoming store promotion. Is that possible through the SpyderWash portal?
**Answer:**
Yes, it is possible to send an email blast to your registered customers about an upcoming store promotion through the SpyderWash portal. The portal allows you to send EMAIL BLASTS to already-registered customers about upcoming promotions or events at your stores.

---

### Q23: How long does a customer typically have to wait before a refunded credit card transaction appears in their bank account?
**Answer:**
According to the provided context, refunds can take 3 to 5 business days to be credited back to the customer.

---

### Q24: How do customers log in to the Spyder Watch Status page or mobile app to check machine availability?
**Answer:**
The provided context does not contain information on how customers log in to the Spyder Watch Status page or mobile app to check machine availability. The context only provides information on how to enable Spyder Watch and view its status from the operator's perspective. I do not have that information in the current KB.

---

### Q25: What specific diagnostic information and machine details should I gather before contacting SpyderWash Support about a configuration issue?
**Answer:**
I do not have that information in the current KB. The provided context only mentions reports and the Attendant Detail Report, but does not specify what diagnostic information or machine details to gather for a configuration issue.

---


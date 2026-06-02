import requests
from bs4 import BeautifulSoup

url = "https://setomaticsystems.com/status"

headers = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8,hi;q=0.7",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "sec-ch-ua": "\"Chromium\";v=\"148\", \"Google Chrome\";v=\"148\", \"Not/A)Brand\";v=\"99\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
}

cookies = {
    "ext_name": "ojplmecpdpgccookcobabopnaifgidhf",
    "_ga": "GA1.1.1681516489.1778237118",
    "_gcl_au": "1.1.559093696.1778237118",
    "__fx": "e2ed6b84-8a74-4c8a-a8ad-2bee738d01ad",
    "mktz_sess": "sess.2.1877927105.1780055812032",
    "mktz_client": "{\"is_returning\":1,\"uid\":\"89116570672681821\",\"session\":\"sess.2.1877927105.1780055812032\",\"views\":1,\"referer_url\":\"\",\"referer_domain\":\"\",\"referer_type\":\"direct\",\"visits\":15,\"landing\":\"https://setomaticsystems.com/status/\",\"enter_at\":\"2026-05-29|17:26:52\",\"first_visit\":\"2026-05-8|16:15:15\",\"last_visit\":\"2026-05-16|13:37:30\",\"last_variation\":\"\",\"utm_source\":false,\"utm_term\":false,\"utm_campaign\":false,\"utm_content\":false,\"utm_medium\":false,\"consent\":\"\",\"device_type\":\"desktop\",\"id_website\":\"24300\"}",
    "_ga_RH63YKJQ7Y": "GS2.1.s1780055814$o32$g0$t1780055923$j60$l0$h0",
}

with requests.Session() as s:
    response = s.get(url, headers=headers, cookies=cookies, timeout=30)
    print(response.status_code)

    soup = BeautifulSoup(response.text, "html.parser")
    root = soup.select_one("#brxe-17a192")
    if not root:
        raise ValueError("Status block not found in the response HTML")

    date_text = root.select_one("h4").get_text(strip=True)
    status_text = root.select_one("h2").get_text(strip=True)
    paragraph_text = root.select_one("p").get_text(" ", strip=True)

    print(date_text)
    print(status_text)
    print(paragraph_text)
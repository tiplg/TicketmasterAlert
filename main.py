# main.py - v1.1
from playwright.sync_api import sync_playwright, TimeoutError
import json
import csv
import time
from datetime import datetime
import requests # Import the requests module
import os # Import os module to check for file existence
import sys # Import sys to control the script's exit code

def send_pushbullet_alert(api_tokens, title, message):
    """Sends a notification via Pushbullet to multiple users."""
    if not api_tokens:
        print("No Pushbullet tokens provided. Skipping notification.")
        return
        
    print("Attempting to send Pushbullet notifications...")
    for token in api_tokens:
        if not token or "YOUR_PUSHBULLET_ACCESS_TOKEN" in token:
            print("Skipping invalid or placeholder token.")
            continue
        
        print(f"Sending alert to token ending in ...{token[-4:]}")
        data = {"type": "note", "title": title, "body": message}
        headers = {"Access-Token": token}
        try:
            response = requests.post('https://api.pushbullet.com/v2/pushes', headers=headers, json=data)
            if response.status_code == 200:
                print(f"✅ Pushbullet alert sent successfully to ...{token[-4:]}!")
            else:
                print(f"❌ Failed to send Pushbullet alert to ...{token[-4:]}: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ An error occurred while sending Pushbullet alert: {e}")

def scrape_ticket_info(url):
    """
    Scrapes detailed ticket information from a given URL using Playwright.
    """
    with sync_playwright() as p:
        
        print("Launching headless browser...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Set a larger viewport for higher resolution screenshots
        page.set_viewport_size({"width": 1000, "height": 2000})
        
        scraped_data = []
        try:
            print(f"Navigating to: {url}")
            page.goto(url, timeout=60000)

            # Handle Cookie Consent Banner
            try:
                print("Checking for cookie consent banner...")
                cookie_button_selector = "#onetrust-accept-btn-handler"
                page.click(cookie_button_selector, timeout=5000)
                print("Accepted cookies.")
            except TimeoutError:
                print("No cookie banner found, or it was already accepted.")
            except Exception as e:
                print(f"An error occurred trying to accept cookies: {e}")

            # Wait for Dynamic Content
            container_selector = '[data-testid="ticketTypeInfo"]'
            print("Waiting for ticket information to load...")
            time.sleep(30)
            page.wait_for_selector(container_selector, state='visible', timeout=30000) 
            print("Ticket information loaded.")

            # Scrape and Sanitize the Structured Data
            print("Scraping ticket details...")
            ticket_containers = page.query_selector_all(container_selector)
            if not ticket_containers:
                print("Could not find any ticket information containers.")
                return []
            for container in ticket_containers:
                spans = container.query_selector_all('span')
                if len(spans) == 4:
                    availability_text = spans[1].inner_text()
                    availability_int = int(availability_text.lower().replace('beschikbaar', '').strip())
                    price_text = spans[3].inner_text()
                    price_float = float(price_text.replace('€', '').replace('per stuk', '').replace(',', '.').strip())
                    ticket_info = {
                        "type": spans[0].inner_text(),
                        "availability": availability_int,
                        "category": spans[2].inner_text(),
                        "price": price_float
                    }
                    scraped_data.append(ticket_info)
            return scraped_data
        except TimeoutError:
            print("The page timed out or the ticket elements were not found in time.")
            screenshot_path = "debug_screenshot.png"
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"Screenshot saved to {screenshot_path} for debugging.")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            print("Closing the browser.")
            browser.close()
            # Return empty list on failure so the script doesn't crash on processing
            return scraped_data


if __name__ == '__main__':
    event_url = "https://www.ticketmaster.nl/event/lowlands-2025-%7C-festivalticket-tickets/658441016"
    output_csv_filename = "tickets_summary_log.csv"
    
    # Read tokens from environment variable for secure and flexible configuration
    tokens_json = os.environ.get('PUSHBULLET_TOKENS_JSON')
    if tokens_json:
        PUSHBULLET_API_TOKENS = json.loads(tokens_json)
    else:
        PUSHBULLET_API_TOKENS = []
    
    PRICE_ALERT_THRESHOLD = 300.0

    print(f"Starting scraper for URL: {event_url}")
    scraped_info = scrape_ticket_info(event_url)

    if scraped_info:
        # Process the data to create a summary
        print("\n--- Processing Data for Summary ---")
        total_tickets = sum(item['availability'] for item in scraped_info)
        sorted_tickets = sorted(scraped_info, key=lambda x: x['price'])
        
        cheapest_price = sorted_tickets[0]['price'] if len(sorted_tickets) > 0 else float('inf')
        most_expensive_price = sorted_tickets[-1]['price'] if len(sorted_tickets) > 0 else 'N/A'
        price_5th_cheapest = sorted_tickets[4]['price'] if len(sorted_tickets) >= 5 else 'N/A'
        price_10th_cheapest = sorted_tickets[9]['price'] if len(sorted_tickets) >= 10 else 'N/A'

        average_price_10_cheapest = 'N/A'
        if len(sorted_tickets) > 0:
            ten_cheapest_prices = [ticket['price'] for ticket in sorted_tickets[:10]]
            average_price_10_cheapest = round(sum(ten_cheapest_prices) / len(ten_cheapest_prices), 2)

        average_price_all = 'N/A'
        if len(sorted_tickets) > 0:
            all_prices = [ticket['price'] for ticket in sorted_tickets]
            average_price_all = round(sum(all_prices) / len(all_prices), 2)

        summary_data = {
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'listings_found': len(scraped_info),
            'total_available_tickets': total_tickets,
            'cheapest_price': cheapest_price if cheapest_price != float('inf') else 'N/A',
            '5th_cheapest_price': price_5th_cheapest,
            '10th_cheapest_price': price_10th_cheapest,
            'most_expensive_price': most_expensive_price,
            'average_price_10_cheapest': average_price_10_cheapest,
            'average_price_all_tickets': average_price_all
        }

        print("\n--- Summary Ticket Information ---")
        print(json.dumps(summary_data, indent=2, ensure_ascii=False))

        # Send Alert if Condition is Met
        if cheapest_price < PRICE_ALERT_THRESHOLD:
            print(f"\nCheap ticket found! Price: €{cheapest_price}")
            alert_title = f"Cheap Ticket Alert: €{cheapest_price}"
            alert_message = (f"A ticket for Lowlands is available for €{cheapest_price}. "
                             f"Total tickets found: {total_tickets}.")
            send_pushbullet_alert(PUSHBULLET_API_TOKENS, alert_title, alert_message)
        else:
            print(f"\nNo tickets found under €{PRICE_ALERT_THRESHOLD}. Cheapest is €{cheapest_price}.")

        # Append Summary to CSV File
        file_exists = os.path.exists(output_csv_filename)
        try:
            with open(output_csv_filename, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=summary_data.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(summary_data)
            print(f"\n✅ Summary data successfully appended to {output_csv_filename}")
        except Exception as e:
            print(f"\n❌ Error saving file: {e}")

    else:
        print("\nNo ticket information was scraped.")

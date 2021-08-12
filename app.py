from flask import Flask, request, abort, jsonify
from selenium import webdriver
from bs4 import BeautifulSoup
from datetime import datetime
import requests
import time
import os

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
from apscheduler.schedulers.background import BackgroundScheduler


# Channel Access Token
line_bot_api = LineBotApi('Put your Channel Access Token')
# Channel Secret
handler = WebhookHandler('Put your Channel Secret')

app = Flask(__name__)


# Global variables
oil_types = [
    'Premium Diesel B7', 
    'Diesel B7', 
    'Diesel', 
    'Diesel B20', 
    'E85', 
    'E20', 
    'Gasohol 91', 
    'Gasohol 95', 
    'NGV'
]
today_prices = []
tmr_prices = []
last_update = None
recal_interval = 3600 # second


def get_price_diff_text(price_a, price_b):
    '''
    Work out price difference betwenn two values
    '''
    price_a = float(price_a)
    price_b = float(price_b)
    price_change = price_b - price_a
    if price_change < 0:
        return '▼' + '{:.2f}'.format(abs(price_change))
    elif price_change > 0:
        return '▲' + '{:.2f}'.format(price_change)
    else:
        return ''

def construct_price_block_flex(petrol_type, today_price, tmr_price):
    '''
    Construct a flex content containing price-related information for one individual petrol type
    '''
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
        {
            "type": "text",
            "text": petrol_type,
            "size": "sm",
            "color": "#555555",
            "flex": 0
        },
        {
            "type": "text",
            "text": today_price,
            "size": "sm",
            "color": "#111111",
            "align": "end",
            "position": "absolute",
            "offsetStart": "45%"
        },
        {
            "type": "text",
            "text": tmr_price,
            "size": "sm",
            "color": "#e83515" if float(today_price) < float(tmr_price) else "#139c1e" if float(today_price) > float(tmr_price) else "#111111",
            "align": "end",
            "position": "absolute",
            "offsetStart": "67%"
        },
        {
            "type": "text",
            "text": get_price_diff_text(today_price, tmr_price),
            "size": "sm",
            "color": "#e83515" if float(today_price) < float(tmr_price) else "#139c1e" if float(today_price) > float(tmr_price) else "#111111",
            "align": "end",
            "position": "relative"
        }
        ]
    }

def construct_price_update_flex_content(date):
    '''
    Construct a complete flex content
    '''
    template = {
        "type": "bubble",
        "size": "giga",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
            {
                "type": "text",
                "text": date,
                "weight": "bold",
                "size": "lg",
                "margin": "none"
            },
            {
                "type": "text",
                "text": "พรุ่งนี้ราคาน้ำมันมีการปรับตัว !",
                "size": "md",
                "wrap": True
            },
            {
                "type": "separator",
                "margin": "xxl"
            },
            {
                "type": "box",
                "layout": "horizontal",
                "contents":  [
                {
                    "type": "text",
                    "text": "ประเภทน้ำมัน",
                    "size": "sm",
                    "color": "#555555",
                    "flex": 0,
                    "margin": "none",
                    "weight": "bold"
                },
                {
                    "type": "text",
                    "text": "ราคาวันนี้",
                    "size": "sm",
                    "color": "#111111",
                    "align": "end",
                    "position": "absolute",
                    "offsetStart": "42%"
                },
                {
                    "type": "text",
                    "text": "ราคาพรุ่งนี้",
                    "size": "sm",
                    "color": "#111111",
                    "align": "end",
                    "position": "absolute",
                    "offsetStart": "63%"
                },
                {
                    "type": "text",
                    "text": "ส่วนต่าง",
                    "size": "sm",
                    "color": "#111111",
                    "align": "end"
                }
                ],
                "margin": "lg",
                "offsetBottom": "none"
            },
            {
                "type": "box",
                "layout": "vertical",
                "margin": "md",
                "spacing": "sm",
                "contents": [
                    construct_price_block_flex(petrol_type, today_price, tmr_price) for petrol_type, today_price, tmr_price in zip(oil_types, today_prices, tmr_prices)
                ]
            },
            {
                "type": "separator",
                "margin": "xxl"
            },
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "md",
                "contents": [
                {
                    "type": "text",
                    "text": "อ้างอิงจาก www.bangchak.com",
                    "color": "#aaaaaa",
                    "size": "xs",
                    "align": "end"
                }
                ]
            }
            ]
        },
        "styles": {
            "footer": {
                "separator": True
            }
        }
    }

    return template

def notify_user(date):
    '''
    Extract latest update date from html source and return
    '''
    flex_template = construct_price_update_flex_content(date)
    flex_message = FlexSendMessage(alt_text='พรุ่งนี้ราคาน้ำมันมีการปรับตัว!', contents=flex_template)
    line_bot_api.broadcast(flex_message)


def get_petrol_prices(html_source):
    '''
    Extract petrol prices from html source and return
    '''
    table = html_source.find('table', class_='oil-table')

    today_prices = []
    tmr_prices = []

    for tbody in table.find('tbody').find_all('tr'):
        row = tbody.find_all('td')
        today_price = row[1].text
        tmr_price = row[2].text
        today_prices.append(today_price)
        tmr_prices.append(tmr_price)

    return today_prices, tmr_prices

def get_last_update_date(html_source):
    '''
    Extract latest update date from html source and return
    '''
    date_div = html_source.find('div', class_='current-date')
    late_update_date = ' '.join(date_div.text.rsplit(' ')[-3:])
    return late_update_date

def update_petrol_price():
    global today_prices, tmr_prices, last_update

    URL = 'https://www.moneybuffalo.in.th/rate/oil-price'

    # Initalise webderive to read html data from source
    driver = webdriver.PhantomJS()
    driver.get(URL)
    driver.find_element_by_class_name('oil-table')
    html_source = BeautifulSoup(driver.page_source, features='html.parser')

    today_prices, tmr_prices = get_petrol_prices(html_source)
    current_date = get_last_update_date(html_source)

    # If there is a change from today price to tomorrow price, notify user
    if today_prices != tmr_prices and last_update != current_date:
        last_update = current_date
        notify_user(current_date)


@app.route("/callback", methods=['POST'])
def callback():
    print(request)
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# @handler.add(MessageEvent, message=TextMessage)
# def handle_message(event):
#     if event.message.text.lower() in ['oil price', 'price', 'petrol price']:
#         text = get_oil_price()
#         message = TextSendMessage(text)
#         line_bot_api.reply_message(event.reply_token, message)
#     else:
#         pass

scheduler = BackgroundScheduler()
scheduler.add_job(func=update_petrol_price, trigger="interval", seconds=recal_interval)
scheduler.start()

if __name__ == "__main__":
    update_petrol_price()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

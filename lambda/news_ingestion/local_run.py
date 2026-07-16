from dotenv import load_dotenv

load_dotenv()

from handler import lambda_handler  # noqa: E402  (must import after load_dotenv)

if __name__ == "__main__":
    result = lambda_handler({"tickers": ["AAPL"]}, None)
    print(result['articles']['AAPL'][0])
    print(result.keys())
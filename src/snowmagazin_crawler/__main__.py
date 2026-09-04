import argparse
import json

from .crawler import crawl


def main():
    parser = argparse.ArgumentParser(description='Archive published Snowmagazin articles.')
    parser.add_argument('--output', default='out', help='Output directory (default: out)')
    parser.add_argument('--limit', type=int, default=None, help='Limit successful articles for smoke runs')
    parser.add_argument('--delay', type=float, default=0.15, help='Delay between fallback article requests')
    args = parser.parse_args()
    summary = crawl(output_dir=args.output, limit=args.limit, delay=args.delay)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()

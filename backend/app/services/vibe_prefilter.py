"""Deterministic Datamart admission policy. Missing enrichment is never invented."""
from dataclasses import dataclass
from typing import Any
import re
from urllib.parse import urlsplit

TITLES = ['Founder', 'CEO', 'Co-Founder', 'CTO', 'VP Engineering',
          'Head of Engineering', 'Director of Engineering', 'Owner',
          'Managing Director', 'Operations Director', 'IT Director',
          'Practice Manager', 'Partner']
INDUSTRIES = ['SaaS', 'software', 'IT services', 'HealthTech', 'healthcare',
              'FinTech', 'financial services', 'Real Estate', 'PropTech',
              'E-commerce', 'ecommerce', 'DTC', 'Analytics', 'MarTech']
EXCLUSIONS = ['education', 'educational', 'university', 'universities', 'school',
              'schools', 'college', 'colleges', 'newsletter', 'newsletters', 'media', 'publication',
              'publishing', 'creators', 'influencers', 'podcasts', 'publications', 'creator', 'influencer', 'podcast', 'nonprofit',
              'non-profit', 'non profit', 'government', 'public company',
              'publicly traded', 'publicly held', 'crypto', 'cryptocurrency',
              'NFT', 'Web3', 'gambling', 'casino', 'agency', 'agencies',
              'marketing agency', 'design studio', 'dev shop', 'development shop',
              'software outsourcing', 'marketing services', 'advertising services',
              'design services', 'web design', 'development agency', 'design shop', 'B2C', 'consumer-only']
SOCIAL_HOSTS = ['linkedin.com', 'facebook.com', 'instagram.com', 'twitter.com',
                'x.com', 'tiktok.com', 'youtube.com', 'youtu.be', 'linktr.ee',
                'substack.com', 'medium.com', 'beehiiv.com', 'patreon.com']


def matches(value: Any, choices: list[str]) -> bool:
    text = str(value or '').casefold()
    return any(re.search(r'(?<!\w)' + re.escape(choice.casefold()) + r'(?!\w)', text)
               for choice in choices)


def country_name(value: Any) -> str:
    text = str(value or '').strip()
    return {'us': 'United States', 'usa': 'United States',
            'united states of america': 'United States',
            'ae': 'United Arab Emirates', 'uae': 'United Arab Emirates'}.get(text.casefold(), text)


def weak_company_url(value: Any) -> bool:
    try:
        raw = str(value or '').strip()
        parsed = urlsplit(raw if '://' in raw else 'https://' + raw)
        host = (parsed.hostname or '').casefold().rstrip('.')
        return (parsed.scheme not in {'http', 'https'} or '.' not in host
                or bool(parsed.username or parsed.password)
                or any(host == domain or host.endswith('.' + domain) for domain in SOCIAL_HOSTS)
                or host.endswith(('.edu', '.gov')))
    except ValueError:
        return True


@dataclass(frozen=True)
class PrefilterResult:
    accepted: bool
    rejection_reasons: list[str]
    review_reasons: list[str]


def prefilter_prospect(prospect: dict[str, Any]) -> PrefilterResult:
    reasons = []
    review = []
    for field in ('company_name', 'person_name', 'title', 'linkedin_url', 'company_url'):
        if not isinstance(prospect.get(field), str) or not prospect[field].strip():
            reasons.append('Missing required field: ' + field)
    if weak_company_url(prospect.get('company_url')):
        reasons.append('Company URL is invalid or a weak social/publication page')
    # Inspect business attributes only: evidence mentioning a customer or a podcast
    # must not turn a software company into a media company.
    text = ' '.join(str(prospect.get(key) or '') for key in (
        'company_name', 'title', 'industry', 'business_model', 'company_type',
        'company_description', 'description'))
    for category in EXCLUSIONS:
        if matches(text, [category]):
            reasons.append('Excluded category: ' + category)
    if str(prospect.get('is_public_company')).casefold() == 'true':
        reasons.append('Public companies are excluded')
    country = country_name(prospect.get('country'))
    if country and country.casefold() not in {'united states', 'united arab emirates'}:
        reasons.append('Outside USA/UAE geography')
    elif not country:
        review.append('Company geography is unknown')
    if not matches(prospect.get('title'), TITLES):
        reasons.append('Title is not a target decision maker')
    for key, low, high in [('employee_count', 1, 50), ('annual_revenue', 500_000, 20_000_000)]:
        value = prospect.get(key)
        try:
            number = float(str(value).replace(',', '').replace('$', ''))
        except (ValueError, TypeError):
            review.append(key + ' is unknown')
        else:
            if not low <= number <= high:
                reasons.append(key + ' is outside the ICP range')
    if not prospect.get('industry'):
        review.append('Industry is unknown')
    elif not matches(prospect['industry'], INDUSTRIES):
        review.append('Industry fit requires verification')
    if not matches(prospect.get('business_model'), ['B2B']):
        review.append('B2B business model requires verification')
    if not matches(prospect.get('company_type'), ['privately held', 'private company', 'private']):
        review.append('Private ownership requires verification')
    if not (prospect.get('has_defined_software_need') is True
            or matches(prospect.get('industry'), ['SaaS', 'software', 'HealthTech', 'FinTech', 'PropTech', 'Analytics', 'MarTech'])):
        review.append('Software or engineering need requires verification')
    return PrefilterResult(not reasons, reasons, review)

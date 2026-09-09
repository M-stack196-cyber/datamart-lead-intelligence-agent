"""Deterministic Datamart admission policy. Missing enrichment is never invented."""
from dataclasses import dataclass
from typing import Any
import re
from urllib.parse import unquote, urlsplit
from app.services.vibe_identity import company_host, normalized_name
from app.services.vibe_signals import prepare_vibe_prospect

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
                'substack.com', 'medium.com', 'beehiiv.com', 'patreon.com',
                'beacons.ai', 'teachable.com', 'thinkific.com', 'kajabi.com',
                'gumroad.com', 'stan.store', 'skool.com', 'eventbrite.com', 'meetup.com']

# Explicit exclusions supplied by the Datamart playbook/production review.
# These are negative examples, never a positive allowlist or inferred facts.
EXCLUDED_BRANDS = {
    "simon sinek": ("simonsinek.com", "personal brand / speaker"),
    "chris do": ("", "personal brand / coaching"),
    "the futur": ("thefutur.com", "creator / training"),
    "poets and quants": ("poetsandquants.com", "publication / education"),
    "technical institute of america": ("", "education / training"),
    "algoexpert": ("", "courses / training"),
    "analyst builder": ("", "courses / training"),
    "shay rowbottom": ("", "personal brand / marketing"),
    "shay rowbottom marketing": ("", "personal brand / marketing"),
    "disrupthr": ("", "events / community brand"),
}
EXCLUSIONS += [
    "institute", "institutes", "academy", "academies", "course", "courses",
    "bootcamp", "bootcamps", "training", "certification", "magazine", "show",
    "speaker", "keynote", "personal brand", "personal branding", "coaching",
    "thought leader", "author", "branding agency", "social media agency",
    "content agency", "events", "community brand", "community", "nonprofits",
]


def company_exclusions(prospect: dict[str, Any]) -> list[str]:
    reasons = []
    host = company_host(prospect.get("company_url"))
    name = normalized_name(str(prospect.get("company_name") or "").replace("&", " and "))
    # Exact brand names/domain suffixes avoid blocking similarly named B2B firms.
    for brand, (domain, category) in EXCLUDED_BRANDS.items():
        if name == brand or (domain and (host == domain or host.endswith("." + domain))):
            reasons.append("Excluded Datamart company: " + category)
    if name and name == normalized_name(prospect.get("person_name")):
        reasons.append("Company is a personal-name brand; not a verified B2B company")
    text = " ".join(str(prospect.get(key) or "") for key in (
        "company_name", "title", "industry", "business_model", "company_type",
    ))
    # Decode paths and split domain words so /courses and acme-training.com match.
    url_text = re.sub(r"[./_-]+", " ", unquote(str(prospect.get("company_url") or "")))
    for category in EXCLUSIONS:
        if matches(text + " " + url_text, [category]):
            reasons.append("Excluded category: " + category)
    # Common concatenated course/newsletter domains lack word separators.
    for marker in ("newsletter", "bootcamp", "academy", "institute", "training", "certification"):
        if marker in host:
            reasons.append("Excluded company domain category: " + marker)
    # A description can describe the company or its customers. Do not reject
    # software merely because it supports, for example, customer training.
    description = str(prospect.get("company_description") or prospect.get("description") or "")
    if matches(description, [
        "personal brand", "marketing agency", "branding agency", "content agency",
        "training company", "training provider", "education company", "online courses",
        "coaching business", "media company", "newsletter publisher", "community brand",
    ]):
        reasons.append("Excluded company description: education / media / personal brand / agency")
    if str(prospect.get("is_public_company")).casefold() == "true":
        reasons.append("Public companies are excluded")
    return list(dict.fromkeys(reasons))


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
        raw = unquote(str(value or '').strip())
        if any(fragment in raw.casefold() for fragment in (
            'linkedin.com/newsletters', 'linkedin.com/in', 'substack.com',
            'medium.com', 'youtube.com', 'linktr.ee', 'beacons.ai',
        )):
            return True
        parsed = urlsplit(raw if '://' in raw else 'https://' + raw)
        host = (parsed.hostname or '').casefold().rstrip('.')
        return (parsed.scheme not in {'http', 'https'} or '.' not in host
                or bool(parsed.username or parsed.password)
                or bool(re.search(r'\s', raw))
                or bool(re.fullmatch(r'[0-9.]+', host))
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
    prospect = prepare_vibe_prospect(prospect)
    reasons = []
    review = []
    for field in ('company_name', 'person_name', 'title', 'linkedin_url', 'company_url'):
        if not isinstance(prospect.get(field), str) or not prospect[field].strip():
            reasons.append('Missing required field: ' + field)
    if weak_company_url(prospect.get('company_url')):
        reasons.append('Company URL is invalid or a weak social/publication page')
    reasons.extend(company_exclusions(prospect))
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
            review.append('Missing company size/revenue/industry data')
        else:
            if not low <= number <= high:
                reasons.append(key + ' is outside the ICP range')
    if not prospect.get('industry'):
        review.append('Missing company size/revenue/industry data')
    elif not matches(prospect['industry'], INDUSTRIES):
        review.append('Industry fit requires verification')
    if not matches(prospect.get('business_model'), ['B2B']):
        review.append('B2B business model requires verification')
    if not matches(prospect.get('company_type'), ['privately held', 'private company', 'private']):
        review.append('Private ownership requires verification')
    if not (prospect.get('has_defined_software_need') is True
            or matches(prospect.get('industry'), ['SaaS', 'software', 'HealthTech', 'FinTech', 'PropTech', 'Analytics', 'MarTech'])):
        review.append('Software or engineering need requires verification')
    if 'Missing company size/revenue/industry data' in review:
        review.append('Good decision-maker title but sparse company data')
    if review:
        review.append('Needs manual verification against Datamart ICP')
    return PrefilterResult(not reasons, list(dict.fromkeys(reasons)), list(dict.fromkeys(review)))

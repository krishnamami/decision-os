import { useEffect } from 'react'
import LandingNav from '../components/landing/LandingNav'
import HeroSection from '../components/landing/HeroSection'
import IntegrationsStrip from '../components/landing/IntegrationsStrip'
import VideoSection from '../components/landing/VideoSection'
import PersonaStrip from '../components/landing/PersonaStrip'
import HowItWorks from '../components/landing/HowItWorks'
import FeaturesGrid from '../components/landing/FeaturesGrid'
import ComplianceSection from '../components/landing/ComplianceSection'
import ProductsGrid from '../components/landing/ProductsGrid'
import SimulationSection from '../components/landing/SimulationSection'
import ImpactSection from '../components/landing/ImpactSection'
import PricingSection from '../components/landing/PricingSection'
import FAQSection from '../components/landing/FAQSection'
import CTASection from '../components/landing/CTASection'
import LandingFooter from '../components/landing/LandingFooter'

// Public marketing landing page. No announcement bar — the hero headline is the
// first thing a visitor sees. Routing (App.tsx) sends unauthenticated visitors
// here at `/`, and authenticated users straight to /pipeline.
export default function Landing({ scrollTo }: { scrollTo?: string }) {
  // /pricing (and similar) deep-links land on the section instead of the top.
  useEffect(() => {
    if (scrollTo) {
      const id = setTimeout(() => document.getElementById(scrollTo)?.scrollIntoView({ behavior: 'smooth' }), 100)
      return () => clearTimeout(id)
    }
  }, [scrollTo])

  return (
    <div id="top" className="min-h-screen scroll-smooth bg-white text-slate-900">
      <LandingNav />
      <main>
        <HeroSection />
        <IntegrationsStrip />
        <VideoSection />
        <PersonaStrip />
        <HowItWorks />
        <FeaturesGrid />
        <ComplianceSection />
        <ProductsGrid />
        <SimulationSection />
        <ImpactSection />
        <PricingSection />
        <FAQSection />
        <CTASection />
      </main>
      <LandingFooter />
    </div>
  )
}

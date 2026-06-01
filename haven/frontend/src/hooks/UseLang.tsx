'use client'
import { useState, useEffect } from 'react'

export type Lang = 'en' | 'hi' | 'mr' | 'ta' | 'te' | 'bn'

const translations: Record<Lang, Record<string, string>> = {
  en: {
    // SOS page
    inImmediateDangerSOS: 'In immediate danger? Call',
    describeSituation: 'Describe Your Situation',
    typeKeywords: 'Type a few keywords. Our AI expands them into a complete message. Even 2-3 words is enough.',
    sosPlaceholder: 'e.g. scared, husband hitting me, locked in room',
    expanding: '⏳ Expanding...',
    createDistressMsg: 'Create Distress Message →',
    // Legal page
    legalGreeting: "Hello. I'm Haven's legal assistant, trained on Indian law. Ask me anything about your legal rights — divorce, custody, restraining orders, or filing complaints. Everything is confidential.",
    legalPlaceholder: 'Ask about your legal rights...',
    questions: 'Questions',
    disclaimer: 'AI guidance only. Consult a qualified lawyer for your specific case.',
    searching: 'Searching...',
    // Therapy page
    therapyGreeting: "Hello, I'm Aria. I'm here for you. This is a safe, private space. How are you feeling right now?",
    // Common
    emergency: 'Emergency',
    back: 'Back',
  },
  hi: {
    inImmediateDangerSOS: 'तुरंत खतरे में हैं? कॉल करें',
    describeSituation: 'अपनी स्थिति बताएं',
    typeKeywords: 'कुछ कीवर्ड टाइप करें। हमारा AI उन्हें एक पूरे संदेश में बदल देगा। 2-3 शब्द भी काफी हैं।',
    sosPlaceholder: 'उदा. डर लग रहा है, पति मार रहा है, कमरे में बंद है',
    expanding: '⏳ संदेश बना रहे हैं...',
    createDistressMsg: 'संदेश बनाएं →',
    legalGreeting: 'नमस्ते। मैं Haven का कानूनी सहायक हूं, भारतीय कानून पर प्रशिक्षित। तलाक, हिरासत, या FIR के बारे में पूछें।',
    legalPlaceholder: 'अपने कानूनी अधिकारों के बारे में पूछें...',
    questions: 'प्रश्न',
    disclaimer: 'यह केवल AI मार्गदर्शन है। अपने मामले के लिए एक योग्य वकील से परामर्श करें।',
    searching: 'खोज रहे हैं...',
    therapyGreeting: 'नमस्ते, मैं आपके लिए यहाँ हूँ। यह एक सुरक्षित, निजी स्थान है। आप अभी कैसा महसूस कर रहे हैं?',
    emergency: 'आपातकाल',
    back: 'वापस',
  },
  mr: {
    inImmediateDangerSOS: 'तात्काळ धोक्यात आहात? कॉल करा',
    describeSituation: 'तुमची परिस्थिती सांगा',
    typeKeywords: 'काही कीवर्ड टाइप करा. आमचे AI त्यांना पूर्ण संदेशात रूपांतरित करेल.',
    sosPlaceholder: 'उदा. भीती वाटत आहे, नवरा मारतो, खोलीत बंद आहे',
    expanding: '⏳ संदेश तयार करत आहे...',
    createDistressMsg: 'संदेश तयार करा →',
    legalGreeting: 'नमस्ते. मी Haven चा कायदेशीर सहाय्यक आहे. घटस्फोट, ताब्यात, किंवा FIR बद्दल विचारा.',
    legalPlaceholder: 'तुमच्या कायदेशीर हक्कांबद्दल विचारा...',
    questions: 'प्रश्न',
    disclaimer: 'हे फक्त AI मार्गदर्शन आहे. तुमच्या प्रकरणासाठी वकिलाशी सल्लामसलत करा.',
    searching: 'शोधत आहे...',
    therapyGreeting: 'नमस्ते, मी तुमच्यासाठी येथे आहे. हे एक सुरक्षित, खाजगी ठिकाण आहे.',
    emergency: 'आपत्कालीन',
    back: 'परत',
  },
  ta: {
    inImmediateDangerSOS: 'உடனடி ஆபத்தில் இருக்கிறீர்களா? அழைக்கவும்',
    describeSituation: 'உங்கள் நிலைமையை விவரிக்கவும்',
    typeKeywords: 'சில முக்கிய வார்த்தைகளை தட்டச்சு செய்யுங்கள். எங்கள் AI அதை முழு செய்தியாக மாற்றும்.',
    sosPlaceholder: 'எ.கா. பயமாக இருக்கிறது, கணவர் அடிக்கிறார், அறையில் பூட்டப்பட்டிருக்கிறேன்',
    expanding: '⏳ விரிவாக்குகிறோம்...',
    createDistressMsg: 'செய்தி உருவாக்கு →',
    legalGreeting: 'வணக்கம். நான் Haven இன் சட்ட உதவியாளர். விவாகரத்து, குழந்தை காவல் பற்றி கேளுங்கள்.',
    legalPlaceholder: 'உங்கள் சட்ட உரிமைகளைப் பற்றி கேளுங்கள்...',
    questions: 'கேள்விகள்',
    disclaimer: 'இது AI வழிகாட்டுதல் மட்டுமே. உங்கள் வழக்கிற்கு தகுதியான வழக்கறிஞரை அணுகவும்.',
    searching: 'தேடுகிறோம்...',
    therapyGreeting: 'வணக்கம், நான் உங்களுக்காக இங்கே இருக்கிறேன். இது பாதுகாப்பான, தனிப்பட்ட இடம்.',
    emergency: 'அவசரகாலம்',
    back: 'திரும்பு',
  },
  te: {
    inImmediateDangerSOS: 'తక్షణ ప్రమాదంలో ఉన్నారా? కాల్ చేయండి',
    describeSituation: 'మీ పరిస్థితిని వివరించండి',
    typeKeywords: 'కొన్ని కీవర్డ్‌లు టైప్ చేయండి. మా AI వాటిని పూర్తి సందేశంగా మారుస్తుంది.',
    sosPlaceholder: 'ఉదా. భయంగా ఉంది, భర్త కొడుతున్నాడు, గదిలో బంధించారు',
    expanding: '⏳ విస్తరిస్తున్నాం...',
    createDistressMsg: 'సందేశం సృష్టించండి →',
    legalGreeting: 'నమస్కారం. నేను Haven యొక్క చట్టపరమైన సహాయకుడిని. విడాకులు, పిల్లల సంరక్షణ గురించి అడగండి.',
    legalPlaceholder: 'మీ చట్టపరమైన హక్కుల గురించి అడగండి...',
    questions: 'ప్రశ్నలు',
    disclaimer: 'ఇది AI మార్గదర్శకత్వం మాత్రమే. మీ కేసుకు అర్హత కలిగిన న్యాయవాదిని సంప్రదించండి.',
    searching: 'వెతుకుతున్నాం...',
    therapyGreeting: 'నమస్కారం, నేను మీ కోసం ఇక్కడ ఉన్నాను. ఇది సురక్షితమైన, ప్రైవేట్ స్థలం.',
    emergency: 'అత్యవసరం',
    back: 'వెనక్కి',
  },
  bn: {
    inImmediateDangerSOS: 'তাৎক্ষণিক বিপদে আছেন? কল করুন',
    describeSituation: 'আপনার পরিস্থিতি বর্ণনা করুন',
    typeKeywords: 'কিছু কীওয়ার্ড টাইপ করুন। আমাদের AI সেগুলিকে একটি সম্পূর্ণ বার্তায় রূপান্তরিত করবে।',
    sosPlaceholder: 'যেমন: ভয় লাগছে, স্বামী মারছে, ঘরে আটকে আছি',
    expanding: '⏳ বিস্তার করছি...',
    createDistressMsg: 'বার্তা তৈরি করুন →',
    legalGreeting: 'নমস্কার। আমি Haven-এর আইনি সহকারী। বিবাহবিচ্ছেদ, সন্তানের হেফাজত সম্পর্কে জিজ্ঞাসা করুন।',
    legalPlaceholder: 'আপনার আইনি অধিকার সম্পর্কে জিজ্ঞাসা করুন...',
    questions: 'প্রশ্ন',
    disclaimer: 'এটি শুধুমাত্র AI নির্দেশিকা। আপনার মামলার জন্য একজন যোগ্য আইনজীবীর পরামর্শ নিন।',
    searching: 'খুঁজছি...',
    therapyGreeting: 'নমস্কার, আমি আপনার জন্য এখানে আছি। এটি একটি নিরাপদ, ব্যক্তিগত স্থান।',
    emergency: 'জরুরি',
    back: 'ফিরে যান',
  },
}

export function getAILanguageInstruction(lang: Lang): string {
  const instructions: Record<Lang, string> = {
    en: 'Respond in English.',
    hi: 'कृपया हिंदी में उत्तर दें।',
    mr: 'कृपया मराठीत उत्तर द्या.',
    ta: 'தயவுசெய்து தமிழில் பதிலளிக்கவும்.',
    te: 'దయచేసి తెలుగులో సమాధానం ఇవ్వండి.',
    bn: 'অনুগ্রহ করে বাংলায় উত্তর দিন।',
  }
  return instructions[lang] || instructions.en
}

export function useLang() {
  const [lang, setLangState] = useState<Lang>('en')

  useEffect(() => {
    const saved = localStorage.getItem('haven_lang') as Lang
    if (saved && translations[saved]) setLangState(saved)
  }, [])

  const setLang = (l: Lang) => {
    setLangState(l)
    localStorage.setItem('haven_lang', l)
  }

  const t = (key: string): string => {
    return translations[lang]?.[key] || translations['en']?.[key] || key
  }

  return { lang, setLang, t }
}
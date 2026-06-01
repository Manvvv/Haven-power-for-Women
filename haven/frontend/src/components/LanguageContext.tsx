'use client'
import { createContext, useContext, useState, useEffect, ReactNode } from 'react'

export type Lang = 'en' | 'hi' | 'gu' | 'mr' | 'te' | 'bn' | 'ta'

export const LANGUAGES: { code: Lang; name: string; native: string; flag: string }[] = [
  { code: 'en', name: 'English',   native: 'English',      flag: '🇬🇧' },
  { code: 'hi', name: 'Hindi',     native: 'हिंदी',         flag: '🇮🇳' },
  { code: 'gu', name: 'Gujarati',  native: 'ગુજરાતી',       flag: '🇮🇳' },
  { code: 'mr', name: 'Marathi',   native: 'मराठी',         flag: '🇮🇳' },
  { code: 'te', name: 'Telugu',    native: 'తెలుగు',        flag: '🇮🇳' },
  { code: 'bn', name: 'Bengali',   native: 'বাংলা',         flag: '🇮🇳' },
  { code: 'ta', name: 'Tamil',     native: 'தமிழ்',         flag: '🇮🇳' },
]

// ── ALL TRANSLATIONS ──────────────────────────────────────────────────────────
export const T: Record<string, Record<Lang, string>> = {
  // ── NAV / HEADER ──
  appName:            { en:'Haven', hi:'हेवन', gu:'હેવન', mr:'हेवन', te:'హేవన్', bn:'হ্যাভেন', ta:'ஹேவன்' },
  tagline:            { en:'A Silent Shield, A Strong Voice', hi:'एक मूक ढाल, एक मजबूत आवाज', gu:'એક મૂક ઢાલ, એક મજબૂત અવાજ', mr:'एक मूक ढाल, एक मजबूत आवाज', te:'ఒక మూగ కవచం, ఒక బలమైన గొంతు', bn:'একটি নীরব ঢাল, একটি শক্তিশালী কণ্ঠ', ta:'ஒரு அமைதி கேடயம், ஒரு வலிமையான குரல்' },
  privateConfidential:{ en:'Private & Confidential', hi:'निजी और गोपनीय', gu:'ખાનગી અને ગોપનીય', mr:'खाजगी आणि गोपनीय', te:'ప్రైవేట్ & రహస్యం', bn:'ব্যক্তিগত ও গোপনীয়', ta:'தனிப்பட்ட & இரகசியம்' },
  dashboard:          { en:'Dashboard', hi:'डैशबोर्ड', gu:'ડેશબોર્ડ', mr:'डॅशबोर्ड', te:'డాష్‌బోర్డ్', bn:'ড্যাশবোর্ড', ta:'டாஷ்போர்டு' },
  home:               { en:'Home', hi:'होम', gu:'હોમ', mr:'होम', te:'హోమ్', bn:'হোম', ta:'முகப்பு' },
  signIn:             { en:'Sign In', hi:'साइन इन', gu:'સાઇન ઇન', mr:'साइन इन', te:'సైన్ ఇన్', bn:'সাইন ইন', ta:'உள்நுழை' },
  getHelp:            { en:'Get Help', hi:'मदद पाएं', gu:'મદદ મેળવો', mr:'मदत मिळवा', te:'సహాయం పొందండి', bn:'সাহায্য নিন', ta:'உதவி பெறுங்கள்' },

  // ── HOME PAGE ──
  heroTitle1:         { en:'A Silent Shield.', hi:'एक मूक ढाल।', gu:'એક મૂક ઢાલ।', mr:'एक मूक ढाल।', te:'ఒక మూగ కవచం।', bn:'একটি নীরব ঢাল।', ta:'ஒரு அமைதி கேடயம்।' },
  heroTitle2:         { en:'A Strong Voice.', hi:'एक मजबूत आवाज़।', gu:'એક મજબૂત અવાજ।', mr:'एक मजबूत आवाज।', te:'ఒక బలమైన గొంతు।', bn:'একটি শক্তিশালী কণ্ঠস্বর।', ta:'ஒரு வலிமையான குரல்।' },
  heroDesc:           { en:'Haven empowers women in abusive situations with discreet AI-powered help — from hidden SOS messages to legal guidance and mental health support.', hi:'हेवन दुर्व्यवहार की स्थितियों में महिलाओं को गुप्त AI सहायता देता है — छिपे SOS संदेशों से लेकर कानूनी मार्गदर्शन और मानसिक स्वास्थ्य सहायता तक।', gu:'હેવન દુર્વ્યવહારની સ્થિતિઓમાં મહિલાઓને ગુપ્ત AI મદદ આપે છે — છુપા SOS સંદેશાઓથી કાનૂની માર્ગદર્શન અને માનસિક સ્વાસ્થ્ય સહાય સુધી।', mr:'हेवन अत्याचाराच्या परिस्थितीत महिलांना गुप्त AI मदत देते — लपलेल्या SOS संदेशांपासून कायदेशीर मार्गदर्शन आणि मानसिक आरोग्य सहाय्यापर्यंत।', te:'హేవన్ హింసాత్మక పరిస్థితుల్లో మహిళలకు రహస్య AI సహాయం అందిస్తుంది — దాచిన SOS సందేశాల నుండి న్యాయ మార్గదర్శకత్వం మరియు మానసిక ఆరోగ్య మద్దతు వరకు।', bn:'হ্যাভেন নির্যাতনের পরিস্থিতিতে মহিলাদের গোপন AI সাহায্য প্রদান করে — লুকানো SOS বার্তা থেকে আইনি নির্দেশনা এবং মানসিক স্বাস্থ্য সহায়তা পর্যন্ত।', ta:'ஹேவன் துஷ்பிரயோக சூழ்நிலைகளில் பெண்களுக்கு இரகசிய AI உதவி வழங்குகிறது — மறைக்கப்பட்ட SOS செய்திகளிலிருந்து சட்ட வழிகாட்டுதல் மற்றும் மன நல ஆதரவு வரை।' },
  getHelpDiscreetly:  { en:'Get Help Discreetly →', hi:'चुपचाप मदद पाएं →', gu:'ચૂપચાપ મદદ મેળવો →', mr:'शांतपणे मदत मिळवा →', te:'రహస్యంగా సహాయం పొందండి →', bn:'গোপনে সাহায্য নিন →', ta:'இரகசியமாக உதவி பெறுங்கள் →' },
  authorityDashboard: { en:'Authority Dashboard', hi:'प्राधिकरण डैशबोर्ड', gu:'ઓથોરિટી ડેશબોર્ડ', mr:'प्राधिकरण डॅशबोर्ड', te:'అధికార డాష్‌బోర్డ్', bn:'কর্তৃপক্ষ ড্যাশবোর্ড', ta:'அதிகார டாஷ்போர்டு' },
  emergencyCall:      { en:'⚡ Emergency: Call', hi:'⚡ आपात: कॉल करें', gu:'⚡ કટોકટી: કૉલ કરો', mr:'⚡ आणीबाणी: कॉल करा', te:'⚡ అత్యవసరం: కాల్ చేయండి', bn:'⚡ জরুরি: কল করুন', ta:'⚡ அவசரம்: அழையுங்கள்' },
  womenHelpline:      { en:'Women Helpline:', hi:'महिला हेल्पलाइन:', gu:'મહિલા હેલ્પલાઇન:', mr:'महिला हेल्पलाइन:', te:'మహిళా హెల్ప్‌లైన్:', bn:'মহিলা হেল্পলাইন:', ta:'பெண்கள் உதவி எண்:' },
  whyHavenMatters:    { en:'Why Haven Matters', hi:'हेवन क्यों जरूरी है', gu:'હેવન શા માટે મહત્વ ધરાવે છે', mr:'हेवन का महत्वाचे आहे', te:'హేవన్ ఎందుకు ముఖ్యం', bn:'কেন হ্যাভেন গুরুত্বপূর্ণ', ta:'ஹேவன் ஏன் முக்கியம்' },

  // ── FEATURES ──
  discreeSOS:         { en:'Discreet SOS', hi:'गुप्त SOS', gu:'ગુપ્ત SOS', mr:'गुप्त SOS', te:'రహస్య SOS', bn:'গোপন SOS', ta:'இரகசிய SOS' },
  discreSOSDesc:      { en:'Hide distress messages inside innocent-looking images using AI steganography. Share on social media safely.', hi:'AI स्टेगनोग्राफी का उपयोग करके निर्दोष दिखने वाली तस्वीरों में संकट संदेश छुपाएं।', gu:'AI સ્ટેગ્નોગ્રાફીનો ઉપયોગ કરીને નિર્દોષ દેખાતી છબીઓમાં તકલીફ સંદેશ છુપાવો।', mr:'AI स्टेगनोग्राफी वापरून निरुपद्रवी दिसणाऱ्या प्रतिमांमध्ये त्रास संदेश लपवा।', te:'AI స్టెగనోగ్రఫీ ఉపయోగించి అమాయక చిత్రాలలో సంకట సందేశాలను దాచండి।', bn:'AI স্টেগানোগ্রাফি ব্যবহার করে নিরীহ দেখতে ছবিতে বিপদ বার্তা লুকান।', ta:'AI ஸ்டெகனோகிராஃபி பயன்படுத்தி அப்பாவி படங்களில் சங்கட செய்திகளை மறைக்கவும்।' },
  mentalHealth:       { en:'Mental Health Support', hi:'मानसिक स्वास्थ्य सहायता', gu:'માનસિક સ્વાસ્થ્ય સહાય', mr:'मानसिक आरोग्य सहाय्य', te:'మానసిక ఆరోగ్య మద్దతు', bn:'মানসিক স্বাস্থ্য সহায়তা', ta:'மன நல ஆதரவு' },
  mentalHealthDesc:   { en:'Talk to a compassionate AI avatar 24/7. Receive personalized coping strategies and emotional support.', hi:'24/7 एक दयालु AI अवतार से बात करें। व्यक्तिगत मुकाबला रणनीतियाँ और भावनात्मक समर्थन प्राप्त करें।', gu:'24/7 દયાળુ AI અવતાર સાથે વાત કરો।', mr:'24/7 दयाळू AI अवतारशी बोला।', te:'24/7 కనికరంగల AI అవతార్‌తో మాట్లాడండి।', bn:'24/7 সহানুভূতিশীল AI অবতারের সাথে কথা বলুন।', ta:'24/7 அனுதாபமான AI அவதாரத்துடன் பேசுங்கள்।' },
  legalGuidance:      { en:'Legal Guidance', hi:'कानूनी मार्गदर्शन', gu:'કાનૂની માર્ગદર્શન', mr:'कायदेशीर मार्गदर्शन', te:'న్యాయ మార్గదర్శకత్వం', bn:'আইনি নির্দেশনা', ta:'சட்ட வழிகாட்டுதல்' },
  legalGuidanceDesc:  { en:'Ask about your legal rights. Our AI law bot gives instant, plain-language answers on Indian law.', hi:'अपने कानूनी अधिकारों के बारे में पूछें। हमारा AI कानून बॉट भारतीय कानून पर तत्काल, सरल उत्तर देता है।', gu:'તમારા કાનૂની અધિકારો વિશે પૂછો।', mr:'तुमच्या कायदेशीर हक्कांबद्दल विचारा।', te:'మీ న్యాయ హక్కుల గురించి అడగండి।', bn:'আপনার আইনি অধিকার সম্পর্কে জিজ্ঞাসা করুন।', ta:'உங்கள் சட்ட உரிமைகளைப் பற்றி கேளுங்கள்।' },
  authorityDB:        { en:'Authority Dashboard', hi:'प्राधिकरण डैशबोर्ड', gu:'ઓથોરિટી ડેશબોર્ડ', mr:'प्राधिकरण डॅशबोर्ड', te:'అధికార డాష్‌బోర్డ్', bn:'কর্তৃপক্ষ ড্যাশবোর্ড', ta:'அதிகார டாஷ்போர்டு' },
  authorityDBDesc:    { en:'For officials: monitor SOS cases, decode hidden messages, and match culprit profiles using AI.', hi:'अधिकारियों के लिए: SOS मामलों की निगरानी करें, छिपे संदेश डिकोड करें।', gu:'અધિકારીઓ માટે: SOS કેસ મોનિટર કરો।', mr:'अधिकाऱ्यांसाठी: SOS प्रकरणे निरीक्षण करा।', te:'అధికారులకు: SOS కేసులు పర్యవేక్షించండి।', bn:'কর্মকর্তাদের জন্য: SOS মামলা পর্যবেক্ষণ করুন।', ta:'அதிகாரிகளுக்கு: SOS வழக்குகளை கண்காணிக்கவும்।' },
  learnMore:          { en:'Learn more', hi:'और जानें', gu:'વધુ જાણો', mr:'अधिक जाणा', te:'మరింత తెలుసుకోండి', bn:'আরও জানুন', ta:'மேலும் அறிக' },

  // ── DASHBOARD ──
  welcomeBack:        { en:'Welcome back,', hi:'वापस स्वागत है,', gu:'પાછા આવ્યા,', mr:'परत स्वागत आहे,', te:'తిరిగి స్వాగతం,', bn:'আবার স্বাগতম,', ta:'மீண்டும் வரவேற்கிறோம்,' },
  hello:              { en:'Hello', hi:'नमस्ते', gu:'નમસ્તે', mr:'नमस्कार', te:'నమస్కారం', bn:'হ্যালো', ta:'வணக்கம்' },
  havenIsHere:        { en:'Haven is here for you. Everything is private and safe.', hi:'हेवन आपके लिए यहां है। सब कुछ निजी और सुरक्षित है।', gu:'હેવન તમારા માટે અહીં છે। બધું ખાનગી અને સુરક્ષિત છે।', mr:'हेवन तुमच्यासाठी येथे आहे। सर्व काही खाजगी आणि सुरक्षित आहे।', te:'హేవన్ మీ కోసం ఇక్కడ ఉంది. అన్నీ ప్రైవేట్ మరియు సురక్షితం।', bn:'হ্যাভেন আপনার জন্য এখানে আছে। সবকিছু ব্যক্তিগত এবং নিরাপদ।', ta:'ஹேவன் உங்களுக்காக இங்கே இருக்கிறது. எல்லாம் தனிப்பட்டது மற்றும் பாதுகாப்பானது।' },
  emergencyPanic:     { en:'🚨 Emergency Panic Button', hi:'🚨 आपातकालीन पैनिक बटन', gu:'🚨 કટોકટી પેનિક બટન', mr:'🚨 आपत्कालीन पॅनिक बटण', te:'🚨 అత్యవసర పానిక్ బటన్', bn:'🚨 জরুরি প্যানিক বাটন', ta:'🚨 அவசர பீதி பொத்தான்' },
  panicDesc:          { en:'Hold for 3 seconds → sends WhatsApp alert + GPS location to your trusted contact', hi:'3 सेकंड दबाएं → आपके विश्वस्त संपर्क को WhatsApp अलर्ट + GPS स्थान भेजें', gu:'3 સેકંડ પકડો → WhatsApp એલર્ટ + GPS સ્થાન મોકલો', mr:'3 सेकंद दाबा → WhatsApp अलर्ट + GPS स्थान पाठवा', te:'3 సెకన్లు పట్టుకోండి → WhatsApp హెచ్చరిక + GPS స్థానం పంపండి', bn:'৩ সেকেন্ড ধরুন → WhatsApp সতর্কতা + GPS অবস্থান পাঠান', ta:'3 வினாடிகள் பிடிக்கவும் → WhatsApp எச்சரிக்கை + GPS இருப்பிடம் அனுப்பவும்' },
  inImmediateDanger:  { en:'In immediate danger?', hi:'तत्काल खतरे में हैं?', gu:'તાત્કાલિક ખતરામાં છો?', mr:'तात्काळ धोक्यात आहात?', te:'తక్షణ ప్రమాదంలో ఉన్నారా?', bn:'তাৎক্ষণিক বিপদে আছেন?', ta:'உடனடி ஆபத்தில் உள்ளீர்களா?' },
  sendDiscreeSOS:     { en:'Send Discreet SOS', hi:'गुप्त SOS भेजें', gu:'ગુપ્ત SOS મોકલો', mr:'गुप्त SOS पाठवा', te:'రహస్య SOS పంపండి', bn:'গোপন SOS পাঠান', ta:'இரகசிய SOS அனுப்பு' },
  sendDiscreSOSDesc:  { en:'Hide a distress message inside an ordinary-looking image. Share on social media safely.', hi:'एक साधारण दिखने वाली तस्वीर में संकट संदेश छुपाएं।', gu:'સામાન્ય દેખાતી છબીમાં તકલીફ સંદેશ છુપાવો।', mr:'सामान्य दिसणाऱ्या प्रतिमेत त्रास संदेश लपवा।', te:'సాధారణ చిత్రంలో సంకట సందేశాన్ని దాచండి।', bn:'সাধারণ দেখতে ছবিতে বিপদ বার্তা লুকান।', ta:'சாதாரண படத்தில் சங்கட செய்தியை மறைக்கவும்।' },
  createSOSImage:     { en:'Create SOS Image', hi:'SOS छवि बनाएं', gu:'SOS છબી બનાવો', mr:'SOS प्रतिमा तयार करा', te:'SOS చిత్రం సృష్టించండి', bn:'SOS ছবি তৈরি করুন', ta:'SOS படம் உருவாக்கு' },
  talkToSomeone:      { en:'Talk to Someone', hi:'किसी से बात करें', gu:'કોઈ સાથે વાત કરો', mr:'कोणाशी तरी बोला', te:'ఎవరితోనైనా మాట్లాడండి', bn:'কারো সাথে কথা বলুন', ta:'யாரோடாவது பேசுங்கள்' },
  talkDesc:           { en:'Our compassionate AI companion Aria is available 24/7 to listen and support you.', hi:'हमारी दयालु AI साथी Aria 24/7 सुनने और आपका समर्थन करने के लिए उपलब्ध है।', gu:'Aria 24/7 ઉપલબ્ધ છે।', mr:'Aria 24/7 उपलब्ध आहे।', te:'Aria 24/7 అందుబాటులో ఉంది।', bn:'Aria 24/7 উপলব্ধ।', ta:'Aria 24/7 கிடைக்கிறது।' },
  startTalking:       { en:'Start Talking', hi:'बात करना शुरू करें', gu:'વાત કરવી શરૂ કરો', mr:'बोलणे सुरू करा', te:'మాట్లాడటం ప్రారంభించండి', bn:'কথা বলা শুরু করুন', ta:'பேசத் தொடங்குங்கள்' },
  knowRights:         { en:'Know Your Rights', hi:'अपने अधिकार जानें', gu:'તમારા અધિકાર જાણો', mr:'तुमचे हक्क जाणा', te:'మీ హక్కులు తెలుసుకోండి', bn:'আপনার অধিকার জানুন', ta:'உங்கள் உரிமைகள் தெரிந்துகொள்ளுங்கள்' },
  knowRightsDesc:     { en:'Ask our AI legal assistant about domestic violence laws, divorce, and custody.', hi:'घरेलू हिंसा कानूनों, तलाक और हिरासत के बारे में पूछें।', gu:'ઘરેલુ હિંસા કાયદા, છૂટાછેડા વિશે પૂછો।', mr:'घरगुती हिंसा कायदे, घटस्फोट याबद्दल विचारा।', te:'గృహ హింస చట్టాల గురించి అడగండి।', bn:'গৃহস্থালি হিংসা আইন সম্পর্কে জিজ্ঞাসা করুন।', ta:'குடும்ப வன்முறை சட்டங்களைப் பற்றி கேளுங்கள்।' },
  askLegalQuestions:  { en:'Ask Legal Questions', hi:'कानूनी प्रश्न पूछें', gu:'કાનૂની પ્રશ્ન પૂછો', mr:'कायदेशीर प्रश्न विचारा', te:'న్యాయ ప్రశ్నలు అడగండి', bn:'আইনি প্রশ্ন করুন', ta:'சட்ட கேள்விகள் கேளுங்கள்' },
  trustedResources:   { en:'Trusted Resources', hi:'विश्वसनीय संसाधन', gu:'વિশ્વસનીય સ્ત્રોત', mr:'विश्वासार्ह संसाधने', te:'నమ్మకమైన వనరులు', bn:'বিশ্বস্ত সম্পদ', ta:'நம்பகமான வளங்கள்' },

  // ── SOS PAGE ──
  describeSituation:  { en:'Describe Your Situation', hi:'अपनी स्थिति बताएं', gu:'તમારી સ્થિતિ જણાવો', mr:'तुमची परिस्थिती सांगा', te:'మీ పరిస్థితి వివరించండి', bn:'আপনার পরিস্থিতি বর্ণনা করুন', ta:'உங்கள் நிலையை விவரிக்கவும்' },
  typeKeywords:       { en:'Type a few keywords. Our AI expands them into a complete message. Even 2-3 words is enough.', hi:'कुछ कीवर्ड टाइप करें। हमारा AI उन्हें एक पूर्ण संदेश में बदलता है। 2-3 शब्द भी काफी हैं।', gu:'થોડા કીવર્ડ ટાઇપ કરો।', mr:'काही कीवर्ड टाइप करा।', te:'కొన్ని కీవర్డ్‌లు టైప్ చేయండి।', bn:'কিছু কীওয়ার্ড টাইপ করুন।', ta:'சில முக்கிய வார்த்தைகள் தட்டச்சு செய்யுங்கள்।' },
  sosPlaceholder:     { en:'e.g. scared, husband hitting me, locked in room', hi:'जैसे: डरी हूँ, पति मार रहा है, कमरे में बंद', gu:'જેમ: ડરી ગઈ, પતિ મારે, ઓરડામાં બંધ', mr:'उदा: घाबरले, नवरा मारतो, खोलीत बंद', te:'ఉదా: భయంగా ఉంది, భర్త కొడుతున్నాడు, గదిలో బంధించాడు', bn:'যেমন: ভয় পাচ্ছি, স্বামী মারছে, ঘরে বন্দী', ta:'எ.கா: பயமாக உள்ளது, கணவன் அடிக்கிறான், அறையில் பூட்டினான்' },
  createDistressMsg:  { en:'Create Distress Message →', hi:'संकट संदेश बनाएं →', gu:'તકલીફ સંદેશ બનાવો →', mr:'त्रास संदेश तयार करा →', te:'సంకట సందేశం సృష్టించండి →', bn:'বিপদ বার্তা তৈরি করুন →', ta:'சங்கட செய்தி உருவாக்கு →' },
  expanding:          { en:'⏳ Expanding...', hi:'⏳ विस्तार हो रहा है...', gu:'⏳ વિસ્તૃત થઈ રહ્યું છે...', mr:'⏳ विस्तारित होत आहे...', te:'⏳ విస్తరిస్తోంది...', bn:'⏳ বিস্তার হচ্ছে...', ta:'⏳ விரிவாக்கப்படுகிறது...' },
  inImmediateDangerSOS:{ en:'In immediate danger? Call', hi:'तत्काल खतरे में? कॉल करें', gu:'તાત્કાલિक ખતरे? ફોન करो', mr:'तात्काळ धोका? कॉल करा', te:'తక్షణ ప్రమాదమా? కాల్ చేయండి', bn:'তাৎক্ষণিক বিপদে? কল করুন', ta:'உடனடி ஆபத்தா? அழையுங்கள்' },

  // ── THERAPY PAGE ──
  ariaGreeting:       { en:"Hello, I'm Aria. I'm here for you. This is a safe, private space — whatever you share stays between us. How are you feeling right now?", hi:'नमस्ते, मैं Aria हूँ। मैं आपके लिए यहाँ हूँ। यह एक सुरक्षित, निजी जगह है। आप अभी कैसा महसूस कर रहे हैं?', gu:'નમસ્તે, હું Aria છું। હું તમારા માટે અહીં છું। તમે હવે કેવું અનુભવ કરો છો?', mr:'नमस्कार, मी Aria आहे. मी तुमच्यासाठी येथे आहे. तुम्हाला आता कसे वाटत आहे?', te:'నమస్కారం, నేను Aria ని. నేను మీ కోసం ఇక్కడ ఉన్నాను. మీకు ఇప్పుడు ఎలా అనిపిస్తోంది?', bn:'হ্যালো, আমি Aria। আমি আপনার জন্য এখানে আছি। আপনি এখন কেমন অনুভব করছেন?', ta:'வணக்கம், நான் Aria. நான் உங்களுக்காக இங்கே இருக்கிறேன். நீங்கள் இப்போது எப்படி உணர்கிறீர்கள்?' },
  therapyPlaceholder: { en:"Tell me how you're feeling...", hi:'मुझे बताएं आप कैसा महसूस कर रहे हैं...', gu:'મને જણાવો તમે કેવું અનુભવ કરો છો...', mr:'मला सांगा तुम्हाला कसे वाटते...', te:'మీకు ఎలా అనిపిస్తోందో చెప్పండి...', bn:'আমাকে বলুন আপনি কেমন অনুভব করছেন...', ta:'நீங்கள் எப்படி உணர்கிறீர்கள் என்று சொல்லுங்கள்...' },
  quickReply1:        { en:'I feel anxious', hi:'मुझे चिंता हो रही है', gu:'મને ચિંતા છે', mr:'मला चिंता वाटते', te:'నాకు ఆందోళనగా ఉంది', bn:'আমি উদ্বিগ্ন অনুভব করছি', ta:'நான் கவலைப்படுகிறேன்' },
  quickReply2:        { en:"I'm feeling scared", hi:'मुझे डर लग रहा है', gu:'મને ડर લાગે છે', mr:'मला भीती वाटते', te:'నాకు భయంగా ఉంది', bn:'আমি ভয় পাচ্ছি', ta:'நான் பயப்படுகிறேன்' },
  quickReply3:        { en:'I need coping strategies', hi:'मुझे सामना करने की रणनीति चाहिए', gu:'મને સામનો કરવાની રણનીતિ જોઈએ', mr:'मला सामना करण्याची रणनीती हवी', te:'నాకు తట్టుకునే వ్యూహాలు అవసరం', bn:'আমার মোকাবেলার কৌশল দরকার', ta:'எனக்கு சமாளிக்கும் உத்திகள் தேவை' },
  quickReply4:        { en:"Tell me I'm not alone", hi:'मुझे बताएं कि मैं अकेली नहीं हूँ', gu:'મને કહો કે હું એકલી નથી', mr:'मला सांगा मी एकटी नाही', te:'నేను ఒంటరిని కాదని చెప్పండి', bn:'আমাকে বলুন আমি একা নই', ta:'நான் தனியாக இல்லை என்று சொல்லுங்கள்' },
  poem:               { en:'Poem', hi:'कविता', gu:'કવિતા', mr:'कविता', te:'కవిత', bn:'কবিতা', ta:'கவிதை' },
  aPoemForYou:        { en:'A Poem for You', hi:'आपके लिए एक कविता', gu:'તમારા માટે એક કવિતા', mr:'तुमच्यासाठी एक कविता', te:'మీ కోసం ఒక కవిత', bn:'আপনার জন্য একটি কবিতা', ta:'உங்களுக்கான ஒரு கவிதை' },
  close:              { en:'Close', hi:'बंद करें', gu:'બંધ', mr:'बंद करा', te:'మూసివేయి', bn:'বন্ধ করুন', ta:'மூடு' },

  // ── LEGAL PAGE ──
  legalGreeting:      { en:"Hello. I'm Haven's legal assistant, trained on Indian law. Ask me anything about your legal rights — divorce, custody, restraining orders, or filing complaints. Everything is confidential.", hi:'नमस्ते। मैं हेवन का कानूनी सहायक हूँ, भारतीय कानून पर प्रशिक्षित। तलाक, हिरासत, प्रतिबंधक आदेश के बारे में पूछें।', gu:'નમસ્તે. હું ભારતીય કાયદા પર પ્રશિક્ષિત કાનૂની સહાયક છું।', mr:'नमस्कार. मी भारतीय कायद्यावर प्रशिक्षित कायदेशीर सहाय्यक आहे।', te:'నమస్కారం. నేను భారత చట్టంలో శిక్షణ పొందిన చట్ట సహాయకుడిని।', bn:'হ্যালো. আমি ভারতীয় আইনে প্রশিক্ষিত আইনি সহকারী।', ta:'வணக்கம். நான் இந்திய சட்டத்தில் பயிற்சி பெற்ற சட்ட உதவியாளன்।' },
  legalPlaceholder:   { en:'Ask about your legal rights...', hi:'अपने कानूनी अधिकारों के बारे में पूछें...', gu:'તમારા કાનૂની અધિકારો વિશે પૂછો...', mr:'तुमच्या कायदेशीर हक्कांबद्दल विचारा...', te:'మీ న్యాయ హక్కుల గురించి అడగండి...', bn:'আপনার আইনি অধিকার সম্পর্কে জিজ্ঞাসা করুন...', ta:'உங்கள் சட்ட உரிமைகளைப் பற்றி கேளுங்கள்...' },
  questions:          { en:'Questions', hi:'प्रश्न', gu:'પ્રશ્નો', mr:'प्रश्न', te:'ప్రశ్నలు', bn:'প্রশ্ন', ta:'கேள்விகள்' },
  searching:          { en:'Searching...', hi:'खोज रहे हैं...', gu:'શોધી રહ્યા છીએ...', mr:'शोधत आहे...', te:'వెతుకుతోంది...', bn:'খুঁজছে...', ta:'தேடுகிறது...' },
  disclaimer:         { en:'Disclaimer: AI guidance only. Consult a qualified lawyer.', hi:'अस्वीकरण: केवल AI मार्गदर्शन। योग्य वकील से परामर्श करें।', gu:'અસ્વીકृति: ફક્ત AI માર্ગદર્શન।', mr:'अस्वीकरण: फक्त AI मार्गदर्शन।', te:'నిరాకరణ: కేవలం AI మార్గదర్శకత్వం।', bn:'দাবিত্যাগ: শুধুমাত্র AI নির্দেশনা।', ta:'மறுப்பு: AI வழிகாட்டுதல் மட்டுமே।' },

  // ── FOOTER ──
  footerText:         { en:"© 2026 Haven · Built with ❤️ for women's safety", hi:'© 2026 हेवन · महिला सुरक्षा के लिए ❤️ से बनाया', gu:'© 2026 હેવન · મહિલા સુરક્ષા માટે ❤️ સાથે બનાવ્યું', mr:'© 2026 हेवन · महिला सुरक्षेसाठी ❤️ ने बनवले', te:'© 2026 హేవన్ · మహిళా భద్రత కోసం ❤️ తో నిర్మించబడింది', bn:'© 2026 হ্যাভেন · মহিলা সুরক্ষার জন্য ❤️ দিয়ে তৈরি', ta:'© 2026 ஹேவன் · பெண்கள் பாதுகாப்பிற்காக ❤️ உடன் கட்டமைக்கப்பட்டது' },
  emergencyFooter:    { en:'Emergency: 112 · Women\'s Helpline: 181 · DV Helpline: 1091', hi:'आपात: 112 · महिला हेल्पलाइन: 181 · DV हेल्पलाइन: 1091', gu:'કટوकटی: 112 · મહિલા: 181 · DV: 1091', mr:'आणीबाणी: 112 · महिला: 181 · DV: 1091', te:'అత్యవసరం: 112 · మహిళా: 181 · DV: 1091', bn:'জরুরি: 112 · মহিলা: 181 · DV: 1091', ta:'அவசரம்: 112 · பெண்கள்: 181 · DV: 1091' },

  // ── PANIC BUTTON ──
  holdInstruction:    { en:'Hold 3 seconds to send emergency alert', hi:'आपातकालीन अलर्ट भेजने के लिए 3 सेकंड दबाएं', gu:'3 સેકंड ধরুন', mr:'3 सेकंद धरा', te:'3 సెకన్లు పట్టుకోండి', bn:'৩ সেকেন্ড ধরুন', ta:'3 வினாடிகள் பிடிக்கவும்' },
  noContact:          { en:'No contact set', hi:'कोई संपर्क नहीं', gu:'કોઈ સంपर्ক નથી', mr:'कोणताही संपर्क नाही', te:'సంప్రదింపు లేదు', bn:'কোনো যোগাযোগ নেই', ta:'தொடர்பு இல்லை' },
  addContact:         { en:'+ Add Contact', hi:'+ संपर्क जोड़ें', gu:'+ સंपर्ক ઉमेरो', mr:'+ संपर्क जोडा', te:'+ సంప్రదింపు జోడించండి', bn:'+ যোগাযোগ যোগ করুন', ta:'+ தொடர்பை சேர்க்கவும்' },
  alertSent:          { en:'Alert Sent!', hi:'अलर्ट भेजा गया!', gu:'એলर्ट मोकल्या!', mr:'अलर्ट पाठवला!', te:'హెచ్చరిక పంపబడింది!', bn:'সতর্কতা পাঠানো হয়েছে!', ta:'எச்சரிக்கை அனுப்பப்பட்டது!' },
}

// ── Context ───────────────────────────────────────────────────────────────────
interface LangContextType {
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: string) => string
}

const LangContext = createContext<LangContextType>({
  lang: 'en',
  setLang: () => {},
  t: (key) => key,
})

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>('en')

  useEffect(() => {
    const saved = localStorage.getItem('haven_lang') as Lang
    if (saved && LANGUAGES.find(l => l.code === saved)) setLangState(saved)
  }, [])

  const setLang = (l: Lang) => {
    setLangState(l)
    localStorage.setItem('haven_lang', l)
  }

  const t = (key: string): string => {
    return T[key]?.[lang] || T[key]?.['en'] || key
  }

  return (
    <LangContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LangContext.Provider>
  )
}

export function useLang() {
  return useContext(LangContext)
}

// ── Language Selector Component ───────────────────────────────────────────────
export function LanguageSelector({ compact = false }: { compact?: boolean }) {
  const { lang, setLang } = useLang()
  const [open, setOpen] = useState(false)
  const current = LANGUAGES.find(l => l.code === lang)!

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          background: 'rgba(190,24,93,0.08)',
          border: '1px solid rgba(190,24,93,0.2)',
          borderRadius: 20, padding: compact ? '5px 10px' : '6px 14px',
          cursor: 'pointer', fontSize: compact ? '0.72rem' : '0.78rem',
          color: '#be185d', fontWeight: 600, whiteSpace: 'nowrap'
        }}
      >
        <span>{current.flag}</span>
        <span>{compact ? current.native.slice(0, 3) : current.native}</span>
        <span style={{ fontSize: '0.6rem' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: '110%', right: 0,
          background: 'white', borderRadius: 14,
          border: '1px solid rgba(190,24,93,0.15)',
          boxShadow: '0 8px 32px rgba(190,24,93,0.15)',
          zIndex: 1000, minWidth: 160, overflow: 'hidden'
        }}>
          {LANGUAGES.map(l => (
            <button
              key={l.code}
              onClick={() => { setLang(l.code); setOpen(false) }}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                width: '100%', padding: '10px 16px',
                background: lang === l.code ? 'rgba(190,24,93,0.08)' : 'white',
                border: 'none', cursor: 'pointer', textAlign: 'left',
                fontSize: '0.82rem', color: lang === l.code ? '#be185d' : '#1a0a12',
                fontWeight: lang === l.code ? 700 : 400,
                borderBottom: '1px solid rgba(190,24,93,0.06)',
                transition: 'background 0.15s'
              }}
              onMouseEnter={e => { if (lang !== l.code) e.currentTarget.style.background = '#fdf2f8' }}
              onMouseLeave={e => { if (lang !== l.code) e.currentTarget.style.background = 'white' }}
            >
              <span style={{ fontSize: '1.1rem' }}>{l.flag}</span>
              <div>
                <div style={{ fontSize: '0.82rem' }}>{l.native}</div>
                <div style={{ fontSize: '0.65rem', color: '#8b6b7d' }}>{l.name}</div>
              </div>
              {lang === l.code && <span style={{ marginLeft: 'auto', color: '#be185d' }}>✓</span>}
            </button>
          ))}
        </div>
      )}

      {/* Click outside to close */}
      {open && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 999 }}
          onClick={() => setOpen(false)}
        />
      )}
    </div>
  )
}

// ── Helper: get AI language instruction ──────────────────────────────────────
export function getAILanguageInstruction(lang: Lang): string {
  const instructions: Record<Lang, string> = {
    en: 'Respond in English.',
    hi: 'हिंदी में जवाब दें। (Respond in Hindi)',
    gu: 'ગુજરાતીમાં જવાબ આપો। (Respond in Gujarati)',
    mr: 'मराठीत उत्तर द्या। (Respond in Marathi)',
    te: 'తెలుగులో సమాధానం ఇవ్వండి। (Respond in Telugu)',
    bn: 'বাংলায় উত্তর দিন। (Respond in Bengali)',
    ta: 'தமிழில் பதில் சொல்லுங்கள். (Respond in Tamil)',
  }
  return instructions[lang]
}
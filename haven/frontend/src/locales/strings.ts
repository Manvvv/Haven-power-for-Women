// frontend/src/locales/strings.ts
// ─────────────────────────────────────────────────────────────────────────────
// Centralized namespaced string table — the single source of truth for UI text
// (spec §3: "Do NOT scatter translations across components").
//
// Coverage policy (spec §2 honesty rule):
//   • en, hi, hinglish  → first-class: authored for every key below.
//   • gu, mr, te, bn, ta → community: pre-existing in-repo translations are
//     PRESERVED (no regression) but only cover the original marketing/UI keys.
//     Newer namespaces (errors/accessibility/crisis/etc.) fall back to English.
//   • kn, ml, pa, or, as → registered for selection; resolve to English until a
//     reviewed translation is added. We do NOT invent them.
//
// Safety-critical crisis strings for regional languages are intentionally left to
// English fallback rather than machine-translated (spec §10).
// ─────────────────────────────────────────────────────────────────────────────
import { StringTable } from './i18n'

export const STRINGS: StringTable = {
  // ── NAVIGATION / HEADER ─────────────────────────────────────────────────────
  navigation: {
    appName:             { en:'Haven', hi:'हेवन', hinglish:'Haven', gu:'હેવન', mr:'हेवन', te:'హేవన్', bn:'হ্যাভেন', ta:'ஹேவன்' },
    tagline:             { en:'A Silent Shield, A Strong Voice', hi:'एक मूक ढाल, एक मजबूत आवाज', hinglish:'Ek khamosh dhaal, ek mazboot awaaz', gu:'એક મૂક ઢાલ, એક મજબૂત અવાજ', mr:'एक मूक ढाल, एक मजबूत आवाज', te:'ఒక మూగ కవచం, ఒక బలమైన గొంతు', bn:'একটি নীরব ঢাল, একটি শক্তিশালী কণ্ঠ', ta:'ஒரு அமைதி கேடயம், ஒரு வலிமையான குரல்' },
    privateConfidential: { en:'Private & Confidential', hi:'निजी और गोपनीय', hinglish:'Private aur confidential', gu:'ખાનગી અને ગોપનીય', mr:'खाजगी आणि गोपनीय', te:'ప్రైవేట్ & రహస్యం', bn:'ব্যক্তিগত ও গোপনীয়', ta:'தனிப்பட்ட & இரகசியம்' },
    dashboard:           { en:'Dashboard', hi:'डैशबोर्ड', hinglish:'Dashboard', gu:'ડેશબોર્ડ', mr:'डॅशबोर्ड', te:'డాష్‌బోర్డ్', bn:'ড্যাশবোর্ড', ta:'டாஷ்போர்டு' },
    home:                { en:'Home', hi:'होम', hinglish:'Home', gu:'હોમ', mr:'होम', te:'హోమ్', bn:'হোম', ta:'முகப்பு' },
    signIn:              { en:'Sign In', hi:'साइन इन', hinglish:'Sign In', gu:'સાઇન ઇન', mr:'साइन इन', te:'సైన్ ఇన్', bn:'সাইন ইন', ta:'உள்நுழை' },
    signUp:              { en:'Sign Up', hi:'साइन अप', hinglish:'Sign Up', gu:'સાઇન અપ', mr:'साइन अप', te:'సైన్ అప్', bn:'সাইন আপ', ta:'பதிவு செய்' },
    getHelp:             { en:'Get Help', hi:'मदद पाएं', hinglish:'Madad paayein', gu:'મદદ મેળવો', mr:'मदत मिळवा', te:'సహాయం పొందండి', bn:'সাহায্য নিন', ta:'உதவி பெறுங்கள்' },
    authorityDashboard:  { en:'Authority Dashboard', hi:'प्राधिकरण डैशबोर्ड', hinglish:'Authority Dashboard', gu:'ઓથોરિટી ડેશબોર્ડ', mr:'प्राधिकरण डॅशबोर्ड', te:'అధికార డాష్‌బోర్డ్', bn:'কর্তৃপক্ষ ড্যাশবোর্ড', ta:'அதிகார டாஷ்போர்டு' },
  },

  // ── COMMON (home / dashboard / features / footer / shared buttons) ───────────
  common: {
    teamBadge:          { en:'🏆 Team - Byte Me', hi:'🏆 टीम - बाइट मी', hinglish:'🏆 Team - Byte Me', gu:'🏆 ટીમ - બાઇટ મી', mr:'🏆 टीम - बाइट मी', te:'🏆 టీమ్ - బైట్ మీ', bn:'🏆 টিম - বাইট মি', ta:'🏆 குழு - பைட் மீ' },
    heroTitle1:         { en:'A Silent Shield.', hi:'एक मूक ढाल।', hinglish:'Ek khamosh dhaal.', gu:'એક મૂક ઢાલ।', mr:'एक मूक ढाल।', te:'ఒక మూగ కవచం।', bn:'একটি নীরব ঢাল।', ta:'ஒரு அமைதி கேடயம்।' },
    heroTitle2:         { en:'A Strong Voice.', hi:'एक मजबूत आवाज़।', hinglish:'Ek mazboot awaaz.', gu:'એક મજબૂત અવાજ।', mr:'एक मजबूत आवाज।', te:'ఒక బలమైన గొంతు।', bn:'একটি শক্তিশালী কণ্ঠস্বর।', ta:'ஒரு வலிமையான குரல்।' },
    heroDesc:           { en:'Haven empowers women in abusive situations with discreet AI-powered help — from hidden SOS messages to legal guidance and mental health support.', hi:'हेवन दुर्व्यवहार की स्थितियों में महिलाओं को गुप्त AI सहायता देता है — छिपे SOS संदेशों से लेकर कानूनी मार्गदर्शन और मानसिक स्वास्थ्य सहायता तक।', hinglish:'Haven abuse ki situations mein mahilaon ko discreet AI madad deta hai — chhupe SOS messages se lekar legal guidance aur mental health support tak.', gu:'હેવન દુર્વ્યવહારની સ્થિતિઓમાં મહિલાઓને ગુપ્ત AI મદદ આપે છે — છુપા SOS સંદેશાઓથી કાનૂની માર્ગદર્શન અને માનસિક સ્વાસ્થ્ય સહાય સુધી।', mr:'हेवन अत्याचाराच्या परिस्थितीत महिलांना गुप्त AI मदत देते — लपलेल्या SOS संदेशांपासून कायदेशीर मार्गदर्शन आणि मानसिक आरोग्य सहाय्यापर्यंत।', te:'హేవన్ హింసాత్మక పరిస్థితుల్లో మహిళలకు రహస్య AI సహాయం అందిస్తుంది — దాచిన SOS సందేశాల నుండి న్యాయ మార్గదర్శకత్వం మరియు మానసిక ఆరోగ్య మద్దతు వరకు।', bn:'হ্যাভেন নির্যাতনের পরিস্থিতিতে মহিলাদের গোপন AI সাহায্য প্রদান করে — লুকানো SOS বার্তা থেকে আইনি নির্দেশনা এবং মানসিক স্বাস্থ্য সহায়তা পর্যন্ত।', ta:'ஹேவன் துஷ்பிரயோக சூழ்நிலைகளில் பெண்களுக்கு இரகசிய AI உதவி வழங்குகிறது — மறைக்கப்பட்ட SOS செய்திகளிலிருந்து சட்ட வழிகாட்டுதல் மற்றும் மன நல ஆதரவு வரை।' },
    getHelpDiscreetly:  { en:'Get Help Discreetly →', hi:'चुपचाप मदद पाएं →', hinglish:'Chupchaap madad paayein →', gu:'ચૂપચાપ મદદ મેળવો →', mr:'शांतपणे मदत मिळवा →', te:'రహస్యంగా సహాయం పొందండి →', bn:'গোপনে সাহায্য নিন →', ta:'இரகசியமாக உதவி பெறுங்கள் →' },
    emergencyCall:      { en:'⚡ Emergency: Call', hi:'⚡ आपात: कॉल करें', hinglish:'⚡ Emergency: Call karein', gu:'⚡ કટોકટી: કૉલ કરો', mr:'⚡ आणीबाणी: कॉल करा', te:'⚡ అత్యవసరం: కాల్ చేయండి', bn:'⚡ জরুরি: কল করুন', ta:'⚡ அவசரம்: அழையுங்கள்' },
    womenHelpline:      { en:'Women Helpline:', hi:'महिला हेल्पलाइन:', hinglish:'Women Helpline:', gu:'મહિલા હેલ્પલાઇન:', mr:'महिला हेल्पलाइन:', te:'మహిళా హెల్ప్‌లైన్:', bn:'মহিলা হেল্পলাইন:', ta:'பெண்கள் உதவி எண்:' },
    whyHavenMatters:    { en:'Why Haven Matters', hi:'हेवन क्यों जरूरी है', hinglish:'Haven kyun zaroori hai', gu:'હેવન શા માટે મહત્વ ધરાવે છે', mr:'हेवन का महत्वाचे आहे', te:'హేవన్ ఎందుకు ముఖ్యం', bn:'কেন হ্যাভেন গুরুত্বপূর্ণ', ta:'ஹேவன் ஏன் முக்கியம்' },
    discreeSOS:         { en:'Discreet SOS', hi:'गुप्त SOS', hinglish:'Discreet SOS', gu:'ગુપ્ત SOS', mr:'गुप्त SOS', te:'రహస్య SOS', bn:'গোপন SOS', ta:'இரகசிய SOS' },
    discreSOSDesc:      { en:'Hide distress messages inside innocent-looking images using AI steganography. Share on social media safely.', hi:'AI स्टेगनोग्राफी का उपयोग करके निर्दोष दिखने वाली तस्वीरों में संकट संदेश छुपाएं।', hinglish:'AI steganography use karke innocent dikhne wali images mein distress messages chhupayein. Social media par safely share karein.', gu:'AI સ્ટેગ્નોગ્રાફીનો ઉપયોગ કરીને નિર્દોષ દેખાતી છબીઓમાં તકલીફ સંદેશ છુપાવો।', mr:'AI स्टेगनोग्राफी वापरून निरुपद्रवी दिसणाऱ्या प्रतिमांमध्ये त्रास संदेश लपवा।', te:'AI స్టెగనోగ్రఫీ ఉపయోగించి అమాయక చిత్రాలలో సంకట సందేశాలను దాచండి।', bn:'AI স্টেগানোগ্রাফি ব্যবহার করে নিরীহ দেখতে ছবিতে বিপদ বার্তা লুকান।', ta:'AI ஸ்டெகனோகிராஃபி பயன்படுத்தி அப்பாவி படங்களில் சங்கட செய்திகளை மறைக்கவும்।' },
    mentalHealth:       { en:'Mental Health Support', hi:'मानसिक स्वास्थ्य सहायता', hinglish:'Mental Health Support', gu:'માનસિક સ્વાસ્થ્ય સહાય', mr:'मानसिक आरोग्य सहाय्य', te:'మానసిక ఆరోగ్య మద్దతు', bn:'মানসিক স্বাস্থ্য সহায়তা', ta:'மன நல ஆதரவு' },
    mentalHealthDesc:   { en:'Talk to a compassionate AI avatar 24/7. Receive personalized coping strategies and emotional support.', hi:'24/7 एक दयालु AI अवतार से बात करें। व्यक्तिगत मुकाबला रणनीतियाँ और भावनात्मक समर्थन प्राप्त करें।', hinglish:'24/7 ek compassionate AI avatar se baat karein. Personalized coping strategies aur emotional support paayein.', gu:'24/7 દયાળુ AI અવતાર સાથે વાત કરો।', mr:'24/7 दयाळू AI अवतारशी बोला।', te:'24/7 కనికరంగల AI అవతార్‌తో మాట్లాడండి।', bn:'24/7 সহানুভূতিশীল AI অবতারের সাথে কথা বলুন।', ta:'24/7 அனுதாபமான AI அவதாரத்துடன் பேசுங்கள்।' },
    legalGuidance:      { en:'Legal Guidance', hi:'कानूनी मार्गदर्शन', hinglish:'Legal Guidance', gu:'કાનૂની માર્ગદર્શન', mr:'कायदेशीर मार्गदर्शन', te:'న్యాయ మార్గదర్శకత్వం', bn:'আইনি নির্দেশনা', ta:'சட்ட வழிகாட்டுதல்' },
    legalGuidanceDesc:  { en:'Ask about your legal rights. Our AI law bot gives instant, plain-language answers on Indian law.', hi:'अपने कानूनी अधिकारों के बारे में पूछें। हमारा AI कानून बॉट भारतीय कानून पर तत्काल, सरल उत्तर देता है।', hinglish:'Apne legal rights ke baare mein poochein. Hamara AI law bot Indian law par instant, simple jawab deta hai.', gu:'તમારા કાનૂની અધિકારો વિશે પૂછો।', mr:'तुमच्या कायदेशीर हक्कांबद्दल विचारा।', te:'మీ న్యాయ హక్కుల గురించి అడగండి।', bn:'আপনার আইনি অধিকার সম্পর্কে জিজ্ঞাসা করুন।', ta:'உங்கள் சட்ட உரிமைகளைப் பற்றி கேளுங்கள்।' },
    authorityDB:        { en:'Authority Dashboard', hi:'प्राधिकरण डैशबोर्ड', hinglish:'Authority Dashboard', gu:'ઓથોરિટી ડેશબોર્ડ', mr:'प्राधिकरण डॅशबोर्ड', te:'అధికార డాష్‌బోర్డ్', bn:'কর্তৃপক্ষ ড্যাশবোর্ড', ta:'அதிகார டாஷ்போர்டு' },
    authorityDBDesc:    { en:'For officials: monitor SOS cases, decode hidden messages, and search case & profile intelligence using AI.', hi:'अधिकारियों के लिए: SOS मामलों की निगरानी करें, छिपे संदेश डिकोड करें।', hinglish:'Officials ke liye: SOS cases monitor karein, chhupe messages decode karein.', gu:'અધિકારીઓ માટે: SOS કેસ મોનિટર કરો।', mr:'अधिकाऱ्यांसाठी: SOS प्रकरणे निरीक्षण करा।', te:'అధికారులకు: SOS కేసులు పర్యవేక్షించండి।', bn:'কর্মকর্তাদের জন্য: SOS মামলা পর্যবেক্ষণ করুন।', ta:'அதிகாரிகளுக்கு: SOS வழக்குகளை கண்காணிக்கவும்।' },
    learnMore:          { en:'Learn more', hi:'और जानें', hinglish:'Aur jaanein', gu:'વધુ જાણો', mr:'अधिक जाणा', te:'మరింత తెలుసుకోండి', bn:'আরও জানুন', ta:'மேலும் அறிக' },
    welcomeBack:        { en:'Welcome back,', hi:'वापस स्वागत है,', hinglish:'Wapas swagat hai,', gu:'પાછા આવ્યા,', mr:'परत स्वागत आहे,', te:'తిరిగి స్వాగతం,', bn:'আবার স্বাগতম,', ta:'மீண்டும் வரவேற்கிறோம்,' },
    hello:              { en:'Hello', hi:'नमस्ते', hinglish:'Namaste', gu:'નમસ્તે', mr:'नमस्कार', te:'నమస్కారం', bn:'হ্যালো', ta:'வணக்கம்' },
    friendFallback:     { en:'there', hi:'दोस्त', hinglish:'dost', gu:'મિત્ર', mr:'मैत्रिणी', te:'మిత్రమా', bn:'বন্ধু', ta:'தோழி' },
    havenIsHere:        { en:'Haven is here for you. Everything is private and safe.', hi:'हेवन आपके लिए यहां है। सब कुछ निजी और सुरक्षित है।', hinglish:'Haven aapke liye yahan hai. Sab kuch private aur safe hai.', gu:'હેવન તમારા માટે અહીં છે। બધું ખાનગી અને સુરક્ષિત છે।', mr:'हेवन तुमच्यासाठी येथे आहे। सर्व काही खाजगी आणि सुरक्षित आहे।', te:'హేవన్ మీ కోసం ఇక్కడ ఉంది. అన్నీ ప్రైవేట్ మరియు సురక్షితం।', bn:'হ্যাভেন আপনার জন্য এখানে আছে। সবকিছু ব্যক্তিগত এবং নিরাপদ।', ta:'ஹேவன் உங்களுக்காக இங்கே இருக்கிறது. எல்லாம் தனிப்பட்டது மற்றும் பாதுகாப்பானது।' },
    emergencyPanic:     { en:'🚨 Emergency Panic Button', hi:'🚨 आपातकालीन पैनिक बटन', hinglish:'🚨 Emergency Panic Button', gu:'🚨 કટોકટી પેનિક બટન', mr:'🚨 आपत्कालीन पॅनिक बटण', te:'🚨 అత్యవసర పానిక్ బటన్', bn:'🚨 জরুরি প্যানিক বাটন', ta:'🚨 அவசர பீதி பொத்தான்' },
    panicDesc:          { en:'Hold for 3 seconds → sends WhatsApp alert + GPS location to your trusted contact', hi:'3 सेकंड दबाएं → आपके विश्वस्त संपर्क को WhatsApp अलर्ट + GPS स्थान भेजें', hinglish:'3 second dabayein → aapke trusted contact ko WhatsApp alert + GPS location bheje', gu:'3 સેકંડ પકડો → WhatsApp એલર્ટ + GPS સ્થાન મોકલો', mr:'3 सेकंद दाबा → WhatsApp अलर्ट + GPS स्थान पाठवा', te:'3 సెకన్లు పట్టుకోండి → WhatsApp హెచ్చరిక + GPS స్థానం పంపండి', bn:'৩ সেকেন্ড ধরুন → WhatsApp সতর্কতা + GPS অবস্থান পাঠান', ta:'3 வினாடிகள் பிடிக்கவும் → WhatsApp எச்சரிக்கை + GPS இருப்பிடம் அனுப்பவும்' },
    inImmediateDanger:  { en:'In immediate danger?', hi:'तत्काल खतरे में हैं?', hinglish:'Turant khatre mein hain?', gu:'તાત્કાલિક ખતરામાં છો?', mr:'तात्काळ धोक्यात आहात?', te:'తక్షణ ప్రమాదంలో ఉన్నారా?', bn:'তাৎক্ষণিক বিপদে আছেন?', ta:'உடனடி ஆபத்தில் உள்ளீர்களா?' },
    sendDiscreeSOS:     { en:'Send Discreet SOS', hi:'गुप्त SOS भेजें', hinglish:'Discreet SOS bhejein', gu:'ગુપ્ત SOS મોકલો', mr:'गुप्त SOS पाठवा', te:'రహస్య SOS పంపండి', bn:'গোপন SOS পাঠান', ta:'இரகசிய SOS அனுப்பு' },
    sendDiscreSOSDesc:  { en:'Hide a distress message inside an ordinary-looking image. Share on social media safely.', hi:'एक साधारण दिखने वाली तस्वीर में संकट संदेश छुपाएं।', hinglish:'Ek ordinary dikhne wali image mein distress message chhupayein. Social media par safely share karein.', gu:'સામાન્ય દેખાતી છબીમાં તકલીફ સંદેશ છુપાવો।', mr:'सामान्य दिसणाऱ्या प्रतिमेत त्रास संदेश लपवा।', te:'సాధారణ చిత్రంలో సంకట సందేశాన్ని దాచండి।', bn:'সাধারণ দেখতে ছবিতে বিপদ বার্তা লুকান।', ta:'சாதாரண படத்தில் சங்கட செய்தியை மறைக்கவும்।' },
    createSOSImage:     { en:'Create SOS Image', hi:'SOS छवि बनाएं', hinglish:'SOS image banayein', gu:'SOS છબી બનાવો', mr:'SOS प्रतिमा तयार करा', te:'SOS చిత్రం సృష్టించండి', bn:'SOS ছবি তৈরি করুন', ta:'SOS படம் உருவாக்கு' },
    talkToSomeone:      { en:'Talk to Someone', hi:'किसी से बात करें', hinglish:'Kisi se baat karein', gu:'કોઈ સાથે વાત કરો', mr:'कोणाशी तरी बोला', te:'ఎవరితోనైనా మాట్లాడండి', bn:'কারো সাথে কথা বলুন', ta:'யாரோடாவது பேசுங்கள்' },
    talkDesc:           { en:'Our compassionate AI companion Aria is available 24/7 to listen and support you.', hi:'हमारी दयालु AI साथी Aria 24/7 सुनने और आपका समर्थन करने के लिए उपलब्ध है।', hinglish:'Hamari compassionate AI companion Aria 24/7 sunne aur aapka support karne ke liye available hai.', gu:'Aria 24/7 ઉપલબ્ધ છે।', mr:'Aria 24/7 उपलब्ध आहे।', te:'Aria 24/7 అందుబాటులో ఉంది।', bn:'Aria 24/7 উপলব্ধ।', ta:'Aria 24/7 கிடைக்கிறது।' },
    startTalking:       { en:'Start Talking', hi:'बात करना शुरू करें', hinglish:'Baat karna shuru karein', gu:'વાત કરવી શરૂ કરો', mr:'बोलणे सुरू करा', te:'మాట్లాడటం ప్రారంభించండి', bn:'কথা বলা শুরু করুন', ta:'பேசத் தொடங்குங்கள்' },
    knowRights:         { en:'Know Your Rights', hi:'अपने अधिकार जानें', hinglish:'Apne rights jaanein', gu:'તમારા અધિકાર જાણો', mr:'तुमचे हक्क जाणा', te:'మీ హక్కులు తెలుసుకోండి', bn:'আপনার অধিকার জানুন', ta:'உங்கள் உரிமைகள் தெரிந்துகொள்ளுங்கள்' },
    knowRightsDesc:     { en:'Ask our AI legal assistant about domestic violence laws, divorce, and custody.', hi:'घरेलू हिंसा कानूनों, तलाक और हिरासत के बारे में पूछें।', hinglish:'Domestic violence laws, divorce aur custody ke baare mein poochein.', gu:'ઘરેલુ હિંસા કાયદા, છૂટાછેડા વિશે પૂછો।', mr:'घरगुती हिंसा कायदे, घटस्फोट याबद्दल विचारा।', te:'గృహ హింస చట్టాల గురించి అడగండి।', bn:'গৃহস্থালি হিংসা আইন সম্পর্কে জিজ্ঞাসা করুন।', ta:'குடும்ப வன்முறை சட்டங்களைப் பற்றி கேளுங்கள்।' },
    askLegalQuestions:  { en:'Ask Legal Questions', hi:'कानूनी प्रश्न पूछें', hinglish:'Legal questions poochein', gu:'કાનૂની પ્રશ્ન પૂછો', mr:'कायदेशीर प्रश्न विचारा', te:'న్యాయ ప్రశ్నలు అడగండి', bn:'আইনি প্রশ্ন করুন', ta:'சட்ட கேள்விகள் கேளுங்கள்' },
    trustedResources:   { en:'Trusted Resources', hi:'विश्वसनीय संसाधन', hinglish:'Trusted resources', gu:'વિશ્વસનીય સ્ત્રોત', mr:'विश्वासार्ह संसाधने', te:'నమ్మకమైన వనరులు', bn:'বিশ্বস্ত সম্পদ', ta:'நம்பகமான வளங்கள்' },
    footerText:         { en:"© 2026 Haven · Built with ❤️ for women's safety", hi:'© 2026 हेवन · महिला सुरक्षा के लिए ❤️ से बनाया', hinglish:"© 2026 Haven · Women's safety ke liye ❤️ se banaya", gu:'© 2026 હેવન · મહિલા સુરક્ષા માટે ❤️ સાથે બનાવ્યું', mr:'© 2026 हेवन · महिला सुरक्षेसाठी ❤️ ने बनवले', te:'© 2026 హేవన్ · మహిళా భద్రత కోసం ❤️ తో నిర్మించబడింది', bn:'© 2026 হ্যাভেন · মহিলা সুরক্ষার জন্য ❤️ দিয়ে তৈরি', ta:'© 2026 ஹேவன் · பெண்கள் பாதுகாப்பிற்காக ❤️ உடன் கட்டமைக்கப்பட்டது' },
    emergencyFooter:    { en:"Emergency: 112 · Women's Helpline: 181 · DV Helpline: 1091", hi:'आपात: 112 · महिला हेल्पलाइन: 181 · DV हेल्पलाइन: 1091', hinglish:'Emergency: 112 · Women Helpline: 181 · DV Helpline: 1091', gu:'કટોકટી: 112 · મહિલા: 181 · DV: 1091', mr:'आणीबाणी: 112 · महिला: 181 · DV: 1091', te:'అత్యవసరం: 112 · మహిళా: 181 · DV: 1091', bn:'জরুরি: 112 · মহিলা: 181 · DV: 1091', ta:'அவசரம்: 112 · பெண்கள்: 181 · DV: 1091' },
    close:              { en:'Close', hi:'बंद करें', hinglish:'Band karein', gu:'બંધ', mr:'बंद करा', te:'మూసివేయి', bn:'বন্ধ করুন', ta:'மூடு' },
    cancel:             { en:'Cancel', hi:'रद्द करें', hinglish:'Cancel karein' },
    confirm:            { en:'Confirm', hi:'पुष्टि करें', hinglish:'Confirm karein' },
    save:               { en:'Save', hi:'सहेजें', hinglish:'Save karein' },
    retry:              { en:'Retry', hi:'पुनः प्रयास करें', hinglish:'Dobara try karein' },
    loading:            { en:'Loading…', hi:'लोड हो रहा है…', hinglish:'Load ho raha hai…' },
    back:               { en:'Back', hi:'वापस', hinglish:'Wapas' },
  },

  auth: {
    accessRestricted:  { en:'Restricted access', hi:'प्रतिबंधित पहुँच', hinglish:'Restricted access' },
    invalidCredentials:{ en:'Invalid credentials. Please try again.', hi:'अमान्य क्रेडेंशियल। कृपया पुनः प्रयास करें।', hinglish:'Invalid credentials. Dobara try karein.' },
    verifying:         { en:'Verifying…', hi:'सत्यापित हो रहा है…', hinglish:'Verify ho raha hai…' },
    signOut:           { en:'Sign Out', hi:'साइन आउट', hinglish:'Sign Out' },
  },

  sos: {
    sos:               { en:'SOS', hi:'SOS', hinglish:'SOS' },
    emergency:         { en:'Emergency', hi:'आपातकाल', hinglish:'Emergency' },
    cancel:            { en:'Cancel', hi:'रद्द करें', hinglish:'Cancel karein' },
    confirm:           { en:'Confirm', hi:'पुष्टि करें', hinglish:'Confirm karein' },
    location:          { en:'Location', hi:'स्थान', hinglish:'Location' },
    sendAlert:         { en:'Send Alert', hi:'अलर्ट भेजें', hinglish:'Alert bhejein' },
    describeSituation: { en:'Describe Your Situation', hi:'अपनी स्थिति बताएं', hinglish:'Apni situation batayein', gu:'તમારી સ્થિતિ જણાવો', mr:'तुमची परिस्थिती सांगा', te:'మీ పరిస్థితి వివరించండి', bn:'আপনার পরিস্থিতি বর্ণনা করুন', ta:'உங்கள் நிலையை விவரிக்கவும்' },
    typeKeywords:      { en:'Type a few keywords. Our AI expands them into a complete message. Even 2-3 words is enough.', hi:'कुछ कीवर्ड टाइप करें। हमारा AI उन्हें एक पूर्ण संदेश में बदलता है। 2-3 शब्द भी काफी हैं।', hinglish:'Kuch keywords type karein. Hamara AI unhe complete message mein badal deta hai. 2-3 shabd bhi kaafi hain.', gu:'થોડા કીવર્ડ ટાઇપ કરો।', mr:'काही कीवर्ड टाइप करा।', te:'కొన్ని కీవర్డ్‌లు టైప్ చేయండి।', bn:'কিছু কীওয়ার্ড টাইপ করুন।', ta:'சில முக்கிய வார்த்தைகள் தட்டச்சு செய்யுங்கள்।' },
    sosPlaceholder:    { en:'e.g. scared, husband hitting me, locked in room', hi:'जैसे: डरी हूँ, पति मार रहा है, कमरे में बंद', hinglish:'jaise: dari hui hoon, husband maar raha hai, kamre mein band', gu:'જેમ: ડરી ગઈ, પતિ મારે, ઓરડામાં બંધ', mr:'उदा: घाबरले, नवरा मारतो, खोलीत बंद', te:'ఉదా: భయంగా ఉంది, భర్త కొడుతున్నాడు, గదిలో బంధించాడు', bn:'যেমন: ভয় পাচ্ছি, স্বামী মারছে, ঘরে বন্দী', ta:'எ.கா: பயமாக உள்ளது, கணவன் அடிக்கிறான், அறையில் பூட்டினான்' },
    createDistressMsg: { en:'Create Distress Message →', hi:'संकट संदेश बनाएं →', hinglish:'Distress message banayein →', gu:'તકલીફ સંદેશ બનાવો →', mr:'त्रास संदेश तयार करा →', te:'సంకట సందేశం సృష్టించండి →', bn:'বিপদ বার্তা তৈরি করুন →', ta:'சங்கட செய்தி உருவாக்கு →' },
    expanding:         { en:'⏳ Expanding…', hi:'⏳ विस्तार हो रहा है…', hinglish:'⏳ Expand ho raha hai…', gu:'⏳ વિસ્તૃત થઈ રહ્યું છે...', mr:'⏳ विस्तारित होत आहे...', te:'⏳ విస్తరిస్తోంది...', bn:'⏳ বিস্তার হচ্ছে...', ta:'⏳ விரிவாக்கப்படுகிறது...' },
    inImmediateDangerSOS:{ en:'In immediate danger? Call', hi:'तत्काल खतरे में? कॉल करें', hinglish:'Turant khatre mein? Call karein', gu:'તાત્કાલિક ખતરે? ફોન કરો', mr:'तात्काळ धोका? कॉल करा', te:'తక్షణ ప్రమాదమా? కాల్ చేయండి', bn:'তাৎক্ষণিক বিপদে? কল করুন', ta:'உடனடி ஆபத்தா? அழையுங்கள்' },
    holdInstruction:   { en:'Hold 3 seconds to send emergency alert', hi:'आपातकालीन अलर्ट भेजने के लिए 3 सेकंड दबाएं', hinglish:'Emergency alert bhejne ke liye 3 second dabayein', gu:'3 સેકંડ ધરો', mr:'3 सेकंद धरा', te:'3 సెకన్లు పట్టుకోండి', bn:'৩ সেকেন্ড ধরুন', ta:'3 வினாடிகள் பிடிக்கவும்' },
    noContact:         { en:'No contact set', hi:'कोई संपर्क नहीं', hinglish:'Koi contact set nahi', gu:'કોઈ સંપર્ક નથી', mr:'कोणताही संपर्क नाही', te:'సంప్రదింపు లేదు', bn:'কোনো যোগাযোগ নেই', ta:'தொடர்பு இல்லை' },
    addContact:        { en:'+ Add Contact', hi:'+ संपर्क जोड़ें', hinglish:'+ Contact add karein', gu:'+ સંપર્ક ઉમેરો', mr:'+ संपर्क जोडा', te:'+ సంప్రదింపు జోడించండి', bn:'+ যোগাযোগ যোগ করুন', ta:'+ தொடர்பை சேர்க்கவும்' },
    alertSent:         { en:'Alert Sent!', hi:'अलर्ट भेजा गया!', hinglish:'Alert bhej diya!', gu:'એલર્ટ મોકલ્યા!', mr:'अलर्ट पाठवला!', te:'హెచ్చరిక పంపబడింది!', bn:'সতর্কতা পাঠানো হয়েছে!', ta:'எச்சரிக்கை அனுப்பப்பட்டது!' },
    trustedContacts:   { en:'Trusted Contacts', hi:'विश्वसनीय संपर्क', hinglish:'Trusted contacts' },
    liveTracking:      { en:'Live Tracking', hi:'लाइव ट्रैकिंग', hinglish:'Live tracking' },
  },

  voice_sos: {
    voiceSos:          { en:'Voice SOS', hi:'वॉइस SOS', hinglish:'Voice SOS' },
    voiceSosEnabled:   { en:'Voice SOS enabled', hi:'वॉइस SOS सक्षम', hinglish:'Voice SOS enabled' },
    voiceSosDisabled:  { en:'Voice SOS disabled', hi:'वॉइस SOS अक्षम', hinglish:'Voice SOS disabled' },
    safeWord:          { en:'Safe word', hi:'सुरक्षित शब्द', hinglish:'Safe word' },
    setupVoiceSos:     { en:'Setup Voice SOS', hi:'वॉइस SOS सेटअप करें', hinglish:'Voice SOS setup karein' },
    listening:         { en:'Listening…', hi:'सुन रहे हैं…', hinglish:'Sun rahe hain…' },
  },
  mental_health: {
    ariaGreeting:      { en:"Hello, I'm Aria. I'm here for you. This is a safe, private space — whatever you share stays between us. How are you feeling right now?", hi:'नमस्ते, मैं Aria हूँ। मैं आपके लिए यहाँ हूँ। यह एक सुरक्षित, निजी जगह है। आप अभी कैसा महसूस कर रहे हैं?', hinglish:'Namaste, main Aria hoon. Main aapke liye yahan hoon. Yeh ek safe, private jagah hai — jo bhi aap share karein woh humare beech rahega. Aap abhi kaisa mehsoos kar rahe hain?', gu:'નમસ્તે, હું Aria છું। હું તમારા માટે અહીં છું। તમે હવે કેવું અનુભવ કરો છો?', mr:'नमस्कार, मी Aria आहे. मी तुमच्यासाठी येथे आहे. तुम्हाला आता कसे वाटत आहे?', te:'నమస్కారం, నేను Aria ని. నేను మీ కోసం ఇక్కడ ఉన్నాను. మీకు ఇప్పుడు ఎలా అనిపిస్తోంది?', bn:'হ্যালো, আমি Aria। আমি আপনার জন্য এখানে আছি। আপনি এখন কেমন অনুভব করছেন?', ta:'வணக்கம், நான் Aria. நான் உங்களுக்காக இங்கே இருக்கிறேன். நீங்கள் இப்போது எப்படி உணர்கிறீர்கள்?' },
    therapyPlaceholder:{ en:"Tell me how you're feeling…", hi:'मुझे बताएं आप कैसा महसूस कर रहे हैं…', hinglish:'Mujhe bataiye aap kaisa mehsoos kar rahe hain…', gu:'મને જણાવો તમે કેવું અનુભવ કરો છો...', mr:'मला सांगा तुम्हाला कसे वाटते...', te:'మీకు ఎలా అనిపిస్తోందో చెప్పండి...', bn:'আমাকে বলুন আপনি কেমন অনুভব করছেন...', ta:'நீங்கள் எப்படி உணர்கிறீர்கள் என்று சொல்லுங்கள்...' },
    quickReply1:       { en:'I feel anxious', hi:'मुझे चिंता हो रही है', hinglish:'Mujhe anxiety ho rahi hai', gu:'મને ચિંતા છે', mr:'मला चिंता वाटते', te:'నాకు ఆందోళనగా ఉంది', bn:'আমি উদ্বিগ্ন অনুভব করছি', ta:'நான் கவலைப்படுகிறேன்' },
    quickReply2:       { en:"I'm feeling scared", hi:'मुझे डर लग रहा है', hinglish:'Mujhe dar lag raha hai', gu:'મને ડર લાગે છે', mr:'मला भीती वाटते', te:'నాకు భయంగా ఉంది', bn:'আমি ভয় পাচ্ছি', ta:'நான் பயப்படுகிறேன்' },
    quickReply3:       { en:'I need coping strategies', hi:'मुझे सामना करने की रणनीति चाहिए', hinglish:'Mujhe coping strategies chahiye', gu:'મને સામનો કરવાની રણનીતિ જોઈએ', mr:'मला सामना करण्याची रणनीती हवी', te:'నాకు తట్టుకునే వ్యూహాలు అవసరం', bn:'আমার মোকাবেলার কৌশল দরকার', ta:'எனக்கு சமாளிக்கும் உத்திகள் தேவை' },
    quickReply4:       { en:"Tell me I'm not alone", hi:'मुझे बताएं कि मैं अकेली नहीं हूँ', hinglish:'Mujhe batayein ki main akeli nahi hoon', gu:'મને કહો કે હું એકલી નથી', mr:'मला सांगा मी एकटी नाही', te:'నేను ఒంటరిని కాదని చెప్పండి', bn:'আমাকে বলুন আমি একা নই', ta:'நான் தனியாக இல்லை என்று சொல்லுங்கள்' },
    poem:              { en:'Poem', hi:'कविता', hinglish:'Poem', gu:'કવિતા', mr:'कविता', te:'కవిత', bn:'কবিতা', ta:'கவிதை' },
    aPoemForYou:       { en:'A Poem for You', hi:'आपके लिए एक कविता', hinglish:'Aapke liye ek poem', gu:'તમારા માટે એક કવિતા', mr:'तुमच्यासाठी एक कविता', te:'మీ కోసం ఒక కవిత', bn:'আপনার জন্য একটি কবিতা', ta:'உங்களுக்கான ஒரு கவிதை' },
    dontSave:          { en:"Don't save this conversation", hi:'यह बातचीत सहेजें नहीं', hinglish:'Yeh conversation save mat karein' },
    statusPrivate:     { en:'Private', hi:'निजी', hinglish:'Private' },
    statusNonJudgmental:{ en:'Non-judgmental', hi:'बिना निर्णय के', hinglish:'Non-judgmental' },
    status247:         { en:'24/7', hi:'24/7', hinglish:'24/7' },
    // ── Crisis panels (reviewed; emergency numbers preserved verbatim) ──
    crisisTitle:       { en:"You're not alone right now", hi:'आप इस समय अकेली नहीं हैं', hinglish:'Aap is waqt akeli nahi hain' },
    crisisBody:        { en:'If you are thinking about harming yourself, please reach out now. Talking to someone can help. You matter.', hi:'यदि आप खुद को नुकसान पहुँचाने के बारे में सोच रहे हैं, तो कृपया अभी संपर्क करें। किसी से बात करना मदद कर सकता है। आप महत्वपूर्ण हैं।', hinglish:'Agar aap khud ko nuksaan pahunchane ke baare mein soch rahe hain, please abhi reach out karein. Kisi se baat karna madad kar sakta hai. Aap important hain.' },
    callTeleManas:     { en:'Call Tele-MANAS — 14416', hi:'Tele-MANAS को कॉल करें — 14416', hinglish:'Tele-MANAS ko call karein — 14416' },
    callEmergency:     { en:'Call emergency services — 112', hi:'आपातकालीन सेवाओं को कॉल करें — 112', hinglish:'Emergency services ko call karein — 112' },
    activateSos:       { en:'Activate HAVEN SOS', hi:'HAVEN SOS सक्रिय करें', hinglish:'HAVEN SOS activate karein' },
    reachContact:      { en:'Reach a trusted contact', hi:'किसी विश्वसनीय संपर्क तक पहुँचें', hinglish:'Kisi trusted contact tak pahunchein' },
    consentNote:       { en:'You choose what happens next. Nothing is contacted automatically.', hi:'आगे क्या होगा यह आप तय करते हैं। कुछ भी स्वतः संपर्क नहीं किया जाता।', hinglish:'Aage kya hoga yeh aap decide karte hain. Kuch bhi automatically contact nahi hota.' },
    calmTitle:         { en:"Let's slow things down", hi:'आइए चीज़ों को धीमा करें', hinglish:'Aaiye cheezon ko dheere karein' },
    breathingHint:     { en:'In for 4 · hold for 4 · out for 6', hi:'4 तक सांस लें · 4 तक रोकें · 6 तक छोड़ें', hinglish:'4 tak saans lein · 4 tak roken · 6 tak chhodein' },
    feelCalmer:        { en:'I feel a little calmer', hi:'मुझे थोड़ा शांत लग रहा है', hinglish:'Mujhe thoda calm lag raha hai' },
    moreHelp:          { en:"I'd like more help", hi:'मुझे और मदद चाहिए', hinglish:'Mujhe aur madad chahiye' },
    talkNow:           { en:'Talk to someone now', hi:'अभी किसी से बात करें', hinglish:'Abhi kisi se baat karein' },
    talkProfessional:  { en:'Talk to a professional', hi:'किसी पेशेवर से बात करें', hinglish:'Kisi professional se baat karein' },
    safetyPlanLink:    { en:'My safety plan & privacy', hi:'मेरी सुरक्षा योजना और गोपनीयता', hinglish:'Meri safety plan aur privacy' },
    btnTalk:           { en:'Talk', hi:'बात करें', hinglish:'Baat karein' },
    btnCalm:           { en:'Calm Down', hi:'शांत हों', hinglish:'Shaant hon' },
    btnGetHelp:        { en:'Get Help', hi:'मदद पाएं', hinglish:'Madad paayein' },
    toggleVoiceOff:    { en:'Turn voice off', hi:'आवाज़ बंद करें', hinglish:'Voice band karein' },
    toggleVoiceOn:     { en:'Turn voice on', hi:'आवाज़ चालू करें', hinglish:'Voice chalu karein' },
    voiceUnavailable:  { en:'Voice unavailable — continuing with text.', hi:'आवाज़ उपलब्ध नहीं — टेक्स्ट के साथ जारी है।', hinglish:'Voice unavailable — text ke saath jaari hai.' },
    generatePoem:      { en:'Generate inspirational poem', hi:'प्रेरणादायक कविता बनाएं', hinglish:'Inspirational poem banayein' },
    goBack:            { en:'Go back', hi:'वापस जाएं', hinglish:'Wapas jaayein' },
  },
  legal: {
    legalGreeting:     { en:"Hello. I'm Haven's legal assistant, trained on Indian law. Ask me anything about your legal rights — divorce, custody, restraining orders, or filing complaints. Everything is confidential.", hi:'नमस्ते। मैं हेवन का कानूनी सहायक हूँ, भारतीय कानून पर प्रशिक्षित। तलाक, हिरासत, प्रतिबंधक आदेश के बारे में पूछें।', hinglish:"Namaste. Main Haven ka legal assistant hoon, Indian law par trained. Divorce, custody, restraining orders ya complaint file karne ke baare mein poochein. Sab kuch confidential hai.", gu:'નમસ્તે. હું ભારતીય કાયદા પર પ્રશિક્ષિત કાનૂની સહાયક છું।', mr:'नमस्कार. मी भारतीय कायद्यावर प्रशिक्षित कायदेशीर सहाय्यक आहे।', te:'నమస్కారం. నేను భారత చట్టంలో శిక్షణ పొందిన చట్ట సహాయకుడిని।', bn:'হ্যালো. আমি ভারতীয় আইনে প্রশিক্ষিত আইনি সহকারী।', ta:'வணக்கம். நான் இந்திய சட்டத்தில் பயிற்சி பெற்ற சட்ட உதவியாளன்।' },
    legalPlaceholder:  { en:'Ask about your legal rights…', hi:'अपने कानूनी अधिकारों के बारे में पूछें…', hinglish:'Apne legal rights ke baare mein poochein…', gu:'તમારા કાનૂની અધિકારો વિશે પૂછો...', mr:'तुमच्या कायदेशीर हक्कांबद्दल विचारा...', te:'మీ న్యాయ హక్కుల గురించి అడగండి...', bn:'আপনার আইনি অধিকার সম্পর্কে জিজ্ঞাসা করুন...', ta:'உங்கள் சட்ட உரிமைகளைப் பற்றி கேளுங்கள்...' },
    questions:         { en:'Questions', hi:'प्रश्न', hinglish:'Questions', gu:'પ્રશ્નો', mr:'प्रश्न', te:'ప్రశ్నలు', bn:'প্রশ্ন', ta:'கேள்விகள்' },
    quickQuestions:    { en:'Quick Questions', hi:'त्वरित प्रश्न', hinglish:'Quick questions', gu:'ઝડપી પ્રશ્નો', mr:'झटपट प्रश्न', te:'త్వరిత ప్రశ్నలు', bn:'দ্রুত প্রশ্ন', ta:'விரைவு கேள்விகள்' },
    searching:         { en:'Searching…', hi:'खोज रहे हैं…', hinglish:'Search ho raha hai…', gu:'શોધી રહ્યા છીએ...', mr:'शोधत आहे...', te:'వెతుకుతోంది...', bn:'খুঁজছে...', ta:'தேடுகிறது...' },
    disclaimer:        { en:'Disclaimer: AI guidance only. Consult a qualified lawyer.', hi:'अस्वीकरण: केवल AI मार्गदर्शन। योग्य वकील से परामर्श करें।', hinglish:'Disclaimer: Sirf AI guidance. Kisi qualified vakil se salah lein.', gu:'અસ્વીકૃતિ: ફક્ત AI માર્ગદર્શન।', mr:'अस्वीकरण: फक्त AI मार्गदर्शन।', te:'నిరాకరణ: కేవలం AI మార్గదర్శకత్వం।', bn:'দাবিত্যাগ: শুধুমাত্র AI নির্দেশনা।', ta:'மறுப்பு: AI வழிகாட்டுதல் மட்டுமே।' },
    officialSource:    { en:'Official source', hi:'आधिकारिक स्रोत', hinglish:'Official source' },
    sources:           { en:'Sources', hi:'स्रोत', hinglish:'Sources' },
    legalTitle:        { en:'Haven · Legal Assistant', hi:'हेवन · कानूनी सहायक', hinglish:'Haven · Legal Assistant', gu:'હેવન · કાનૂની સહાયક', mr:'हेवन · कायदेशीर सहाय्यक', te:'హేవెన్ · న్యాయ సహాయకుడు', bn:'হেভেন · আইনি সহকারী', ta:'ஹேவன் · சட்ட உதவியாளர்' },
    legalSubtitle:     { en:'Indian Law · Confidential', hi:'भारतीय कानून · गोपनीय', hinglish:'Indian Law · Confidential', gu:'ભારતીય કાયદો · ગોપનીય', mr:'भारतीय कायदा · गोपनीय', te:'భారత చట్టం · గోప్యం', bn:'ভারতীয় আইন · গোপনীয়', ta:'இந்திய சட்டம் · ரகசியம்' },
  },

  authority: {
    authorityAccess:   { en:'Authority Access', hi:'प्राधिकरण पहुँच', hinglish:'Authority Access' },
    officersOnly:      { en:'Restricted to authorized officers', hi:'केवल अधिकृत अधिकारियों के लिए', hinglish:'Sirf authorized officers ke liye' },
    enterDashboard:    { en:'Enter Dashboard', hi:'डैशबोर्ड में प्रवेश करें', hinglish:'Dashboard mein enter karein' },
    sosCases:          { en:'SOS Cases', hi:'SOS मामले', hinglish:'SOS Cases' },
    loadingCases:      { en:'Loading cases…', hi:'मामले लोड हो रहे हैं…', hinglish:'Cases load ho rahe hain…' },
    noCases:           { en:'No cases yet', hi:'अभी तक कोई मामला नहीं', hinglish:'Abhi tak koi case nahi' },
    refresh:           { en:'Refresh', hi:'रिफ्रेश', hinglish:'Refresh' },
    newSosReceived:    { en:'New SOS Received', hi:'नया SOS प्राप्त हुआ', hinglish:'Naya SOS mila' },
  },

  admin: {
    adminCenter:       { en:'Administration & Audit Center', hi:'प्रशासन और लेखा परीक्षा केंद्र', hinglish:'Administration & Audit Center' },
    verifyingAccess:   { en:'Verifying access…', hi:'पहुँच सत्यापित हो रही है…', hinglish:'Access verify ho raha hai…' },
    securityAudit:     { en:'Security Audit Trail', hi:'सुरक्षा लेखा परीक्षा', hinglish:'Security Audit Trail' },
    userRoleMgmt:      { en:'User & Role Management', hi:'उपयोगकर्ता और भूमिका प्रबंधन', hinglish:'User & Role Management' },
    systemStatus:      { en:'System Status & Configuration', hi:'सिस्टम स्थिति और कॉन्फ़िगरेशन', hinglish:'System Status & Configuration' },
    previous:          { en:'Previous', hi:'पिछला', hinglish:'Previous' },
    next:              { en:'Next', hi:'अगला', hinglish:'Next' },
  },

  notifications: {
    sosNotification:   { en:'SOS alert triggered', hi:'SOS अलर्ट सक्रिय हुआ', hinglish:'SOS alert trigger hua' },
    securityAlert:     { en:'Security alert', hi:'सुरक्षा चेतावनी', hinglish:'Security alert' },
    caseUpdate:        { en:'Case status updated', hi:'मामले की स्थिति अपडेट हुई', hinglish:'Case status update hua' },
    systemNotice:      { en:'System notice', hi:'सिस्टम सूचना', hinglish:'System notice' },
  },
  errors: {
    genericError:      { en:'Something went wrong. Please try again.', hi:'कुछ गलत हो गया। कृपया पुनः प्रयास करें।', hinglish:'Kuch galat ho gaya. Please dobara try karein.', gu:'કંઈક ખોટું થયું. ફરી પ્રયાસ કરો.', mr:'काहीतरी चूक झाली. पुन्हा प्रयत्न करा.', te:'ఏదో తప్పు జరిగింది. దయచేసి మళ్లీ ప్రయత్నించండి.', bn:'কিছু ভুল হয়েছে. আবার চেষ্টা করুন.', ta:'ஏதோ தவறு நடந்தது. மீண்டும் முயற்சிக்கவும்.' },
    networkError:      { en:'Network error. Check your connection.', hi:'नेटवर्क त्रुटि। अपना कनेक्शन जाँचें।', hinglish:'Network error. Apna connection check karein.', gu:'નેટવર્ક ભૂલ. તમારું કનેક્શન તપાસો.', mr:'नेटवर्क त्रुटी. तुमचे कनेक्शन तपासा.', te:'నెట్‌వర్క్ లోపం. మీ కనెక్షన్ తనిఖీ చేయండి.', bn:'নেটওয়ার্ক ত্রুটি. আপনার সংযোগ পরীক্ষা করুন.', ta:'நெட்வொர்க் பிழை. உங்கள் இணைப்பைச் சரிபார்க்கவும்.' },
    aiUnavailable:     { en:'The assistant is temporarily unavailable. Your safety comes first — if this is an emergency, use the SOS button or call 112.', hi:'सहायक अस्थायी रूप से अनुपलब्ध है। आपकी सुरक्षा पहले — आपातकाल में SOS बटन का उपयोग करें या 112 पर कॉल करें।', hinglish:'Assistant abhi temporarily unavailable hai. Aapki safety pehle — emergency mein SOS button use karein ya 112 par call karein.' },
    sessionExpired:    { en:'Your session expired. Please sign in again.', hi:'आपका सत्र समाप्त हो गया। कृपया पुनः साइन इन करें।', hinglish:'Aapka session expire ho gaya. Please dobara sign in karein.' },
    notFound:          { en:'Page not found.', hi:'पृष्ठ नहीं मिला।', hinglish:'Page nahi mila.', gu:'પૃષ્ઠ મળ્યું નથી.', mr:'पृष्ठ सापडले नाही.', te:'పేజీ కనుగొనబడలేదు.', bn:'পৃষ্ঠা পাওয়া যায়নি.', ta:'பக்கம் கிடைக்கவில்லை.' },
    permissionDenied:  { en:'You do not have permission to view this.', hi:'आपको इसे देखने की अनुमति नहीं है।', hinglish:'Aapko yeh dekhne ki permission nahi hai.' },
  },

  accessibility: {
    openMenu:          { en:'Open menu', hi:'मेनू खोलें', hinglish:'Menu kholein', gu:'મેનૂ ખોલો', mr:'मेनू उघडा', te:'మెనూ తెరవండి', bn:'মেনু খুলুন', ta:'மெனுவைத் திற' },
    closeMenu:         { en:'Close menu', hi:'मेनू बंद करें', hinglish:'Menu band karein', gu:'મેનૂ બંધ કરો', mr:'मेनू बंद करा', te:'మెనూ మూసివేయండి', bn:'মেনু বন্ধ করুন', ta:'மெனுவை மூடு' },
    selectLanguage:    { en:'Select language', hi:'भाषा चुनें', hinglish:'Bhasha chunein', gu:'ભાષા પસંદ કરો', mr:'भाषा निवडा', te:'భాష ఎంచుకోండి', bn:'ভাষা নির্বাচন করুন', ta:'மொழியைத் தேர்ந்தெடு' },
    sosButtonLabel:    { en:'Emergency SOS button', hi:'आपातकालीन SOS बटन', hinglish:'Emergency SOS button', gu:'કટોકટી SOS બટન', mr:'आणीबाणी SOS बटण', te:'అత్యవసర SOS బటన్', bn:'জরুরি SOS বোতাম', ta:'அவசர SOS பொத்தான்' },
    loadingContent:    { en:'Loading content', hi:'सामग्री लोड हो रही है', hinglish:'Content load ho raha hai' },
    sendMessage:       { en:'Send message', hi:'संदेश भेजें', hinglish:'Message bhejein', gu:'સંદેશ મોકલો', mr:'संदेश पाठवा', te:'సందేశం పంపండి', bn:'বার্তা পাঠান', ta:'செய்தி அனுப்பு' },
    userAvatar:        { en:'User avatar', hi:'उपयोगकर्ता अवतार', hinglish:'User avatar' },
  },

  resources: {
    emergencyResources:{ en:'Emergency Resources', hi:'आपातकालीन संसाधन', hinglish:'Emergency Resources' },
    nationalEmergency: { en:'National Emergency', hi:'राष्ट्रीय आपातकाल', hinglish:'National Emergency' },
    womenHelpline:     { en:"Women's Helpline", hi:'महिला हेल्पलाइन', hinglish:"Women's Helpline" },
    mentalHealthLine:  { en:'Mental Health Helpline (Tele-MANAS)', hi:'मानसिक स्वास्थ्य हेल्पलाइन (टेली-मानस)', hinglish:'Mental Health Helpline (Tele-MANAS)' },
    childHelpline:     { en:'Child Helpline', hi:'बाल हेल्पलाइन', hinglish:'Child Helpline' },
    policeLabel:       { en:'Police', hi:'पुलिस', hinglish:'Police' },
    ambulanceLabel:    { en:'Ambulance', hi:'एम्बुलेंस', hinglish:'Ambulance' },
    available247:      { en:'Available 24/7', hi:'24/7 उपलब्ध', hinglish:'24/7 available' },
    callNow:           { en:'Call now', hi:'अभी कॉल करें', hinglish:'Abhi call karein' },
  },
}


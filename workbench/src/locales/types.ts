export interface Locale {
  sections: {
    hero: string;
    console: string;
    recommend: string;
    digestTracking: string;
    multimedia: string;
    library: string;
    delivery: string;
    deploy: string;
  };
  header: {
    author: string;
    github: string;
    toggleLang: string;
    toggleTheme: string;
  };
  hero: {
    badge: string;
    title: string;
    subtitle: string;
    tags: string[];
    btnDeploy: string;
    btnDocs: string;
  };
  console: {
    title: string;
    pills: string[];
    cards: {
      lightweight: { title: string; desc: string };
      templates: { title: string; desc: string };
    };
  };
  recommend: {
    title: string;
    pills: string[];
    cards: {
      sources: { title: string; desc: string };
      scoring: { title: string; desc: string };
      filtering: { title: string; desc: string };
    };
  };
  digestTracking: {
    title: string;
    cards: {
      methodFormula: { title: string; desc: string };
      experimentAudit: { title: string; desc: string };
      questionTracking: { title: string; desc: string };
      subQuestions: { title: string; desc: string };
    };
  };
  multimedia: {
    title: string;
    pills: string[];
    cards: {
      podcast: { title: string; desc: string };
      briefing: { title: string; desc: string };
      pptx: { title: string; desc: string };
      videoPoster: { title: string; desc: string };
    };
  };
  library: {
    title: string;
    pills: string[];
    cards: {
      nativeLibrary: { title: string; desc: string };
      ingestionNotes: { title: string; desc: string };
      agentBridge: { title: string; desc: string };
    };
  };
  delivery: {
    title: string;
    pills: string[];
    cards: {
      feishu: { title: string; desc: string };
      email: { title: string; desc: string };
      wechat: { title: string; desc: string };
      telegram: { title: string; desc: string };
    };
  };
  deploy: {
    title: string;
    pills: string[];
    cards: {
      githubActions: { title: string; desc: string };
      agentRetrieval: { title: string; desc: string };
      webhook: { title: string; desc: string };
    };
    steps: {
      fork: { title: string; desc: string };
      wizard: { title: string; desc: string };
      generate: { title: string; desc: string };
    };
    terminal: {
      initDesc: string;
      searchDesc: string;
      copied: string;
      copy: string;
    };
  };
  footer: {
    author: string;
    repo: string;
  };
}

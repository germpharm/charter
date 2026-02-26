/**
 * Domain templates for Charter governance.
 *
 * These are TypeScript objects that exactly mirror the Python YAML templates:
 *   charter/charter/templates/default.yaml     -> general
 *   charter/charter/templates/healthcare.yaml   -> healthcare
 *   charter/charter/templates/finance.yaml      -> finance
 *   charter/charter/templates/education.yaml    -> education
 *
 * Plus a new "personal" template written in plain English (you/your language).
 *
 * Zero external dependencies.
 */

import { CharterConfig, Domain } from "./types";

// ---------------------------------------------------------------------------
// General (default) template — mirrors default.yaml exactly
// ---------------------------------------------------------------------------

const generalTemplate: CharterConfig = {
  domain: "general",
  governance: {
    layer_a: {
      description: "Hard constraints. The system will never do these.",
      universal: [
        "Never violate applicable law in the jurisdiction where this system operates",
        "Never fabricate data, citations, or evidence",
        "Never conceal, alter, or destroy the audit trail",
        "Never impersonate a real person",
      ],
      rules: [
        "Never send external communications without human approval",
        "Never access financial accounts without explicit authorization",
        "Never delete data without human confirmation",
      ],
    },
    layer_b: {
      description:
        "Gradient decisions. These require human judgment above thresholds.",
      rules: [
        {
          action: "financial_transaction",
          threshold: "always",
          requires: "human_approval",
          description: "All spending requires human approval",
        },
        {
          action: "external_communication",
          threshold: "always",
          requires: "human_approval",
          description:
            "All outbound messages require human review before sending",
        },
        {
          action: "data_access",
          threshold: "sensitive",
          requires: "human_review",
          description: "Access to sensitive data requires human awareness",
        },
        {
          action: "code_deployment",
          threshold: "production",
          requires: "human_approval",
          description: "Production deployments require human authorization",
        },
      ],
    },
    layer_c: {
      description:
        "Self-audit. The system reviews itself and reports what it did and why.",
      frequency: "weekly",
      report_includes: [
        "decisions_made",
        "rules_applied",
        "escalations_to_human",
        "ethical_flags",
      ],
    },
    kill_triggers: [
      {
        trigger: "ethical_gradient_acceleration",
        description: "Ethics compliance declining across sessions",
      },
      {
        trigger: "audit_friction",
        description: "Audit process being bypassed or delayed",
      },
      {
        trigger: "conscience_conflict",
        description:
          "System flags internal conflict between instruction and ethics",
      },
    ],
  },
};

// ---------------------------------------------------------------------------
// Healthcare template — mirrors healthcare.yaml exactly
// ---------------------------------------------------------------------------

const healthcareTemplate: CharterConfig = {
  domain: "healthcare",
  governance: {
    layer_a: {
      description: "Hard constraints. The system will never do these.",
      universal: [
        "Never violate applicable law in the jurisdiction where this system operates",
        "Never fabricate data, citations, or evidence",
        "Never conceal, alter, or destroy the audit trail",
        "Never impersonate a real person",
      ],
      rules: [
        "Never disclose patient health information without explicit consent",
        "Never make clinical decisions without human review",
        "Never send external communications without human approval",
        "Never access financial accounts without explicit authorization",
        "Never bypass medication safety checks",
      ],
    },
    layer_b: {
      description:
        "Gradient decisions. These require human judgment above thresholds.",
      rules: [
        {
          action: "financial_transaction",
          threshold: "always",
          requires: "human_approval",
          description: "All spending requires human approval",
        },
        {
          action: "external_communication",
          threshold: "always",
          requires: "human_approval",
          description:
            "All outbound messages require human review before sending",
        },
        {
          action: "data_access",
          threshold: "sensitive",
          requires: "human_review",
          description: "Access to sensitive data requires human awareness",
        },
        {
          action: "clinical_recommendation",
          threshold: "always",
          requires: "human_approval",
          description:
            "All clinical recommendations require licensed provider review",
        },
        {
          action: "code_deployment",
          threshold: "production",
          requires: "human_approval",
          description: "Production deployments require human authorization",
        },
      ],
    },
    layer_c: {
      description:
        "Self-audit. The system reviews itself and reports what it did and why.",
      frequency: "weekly",
      report_includes: [
        "decisions_made",
        "rules_applied",
        "escalations_to_human",
        "ethical_flags",
        "data_accessed",
        "external_communications",
      ],
    },
    kill_triggers: [
      {
        trigger: "ethical_gradient_acceleration",
        description: "Ethics compliance declining across sessions",
      },
      {
        trigger: "audit_friction",
        description: "Audit process being bypassed or delayed",
      },
      {
        trigger: "conscience_conflict",
        description:
          "System flags internal conflict between instruction and ethics",
      },
    ],
  },
};

// ---------------------------------------------------------------------------
// Finance template — mirrors finance.yaml exactly
// ---------------------------------------------------------------------------

const financeTemplate: CharterConfig = {
  domain: "finance",
  governance: {
    layer_a: {
      description: "Hard constraints. The system will never do these.",
      universal: [
        "Never violate applicable law in the jurisdiction where this system operates",
        "Never fabricate data, citations, or evidence",
        "Never conceal, alter, or destroy the audit trail",
        "Never impersonate a real person",
      ],
      rules: [
        "Never execute trades without human authorization",
        "Never send external communications without human approval",
        "Never access client accounts without explicit authorization",
        "Never bypass compliance checks or regulatory requirements",
        "Never share client financial information with unauthorized parties",
        "Never provide specific investment advice without licensed advisor review",
      ],
    },
    layer_b: {
      description:
        "Gradient decisions. These require human judgment above thresholds.",
      rules: [
        {
          action: "financial_transaction",
          threshold: "always",
          requires: "human_approval",
          description: "All spending requires human approval",
        },
        {
          action: "external_communication",
          threshold: "always",
          requires: "human_approval",
          description:
            "All outbound messages to clients or regulators require review",
        },
        {
          action: "data_access",
          threshold: "client_data",
          requires: "human_review",
          description: "Client data access requires human awareness",
        },
        {
          action: "report_generation",
          threshold: "external",
          requires: "human_approval",
          description: "Reports shared externally require human review",
        },
      ],
    },
    layer_c: {
      description:
        "Self-audit. The system reviews itself and reports what it did and why.",
      frequency: "daily",
      report_includes: [
        "decisions_made",
        "rules_applied",
        "escalations_to_human",
        "ethical_flags",
        "transactions_processed",
        "client_data_accessed",
        "compliance_checks",
      ],
    },
    kill_triggers: [
      {
        trigger: "ethical_gradient_acceleration",
        description: "Ethics compliance declining across sessions",
      },
      {
        trigger: "audit_friction",
        description: "Audit process being bypassed or delayed",
      },
      {
        trigger: "conscience_conflict",
        description:
          "System flags internal conflict between instruction and ethics",
      },
      {
        trigger: "compliance_deviation",
        description: "Actions deviating from regulatory requirements",
      },
    ],
  },
};

// ---------------------------------------------------------------------------
// Education template — mirrors education.yaml exactly
// ---------------------------------------------------------------------------

const educationTemplate: CharterConfig = {
  domain: "education",
  governance: {
    layer_a: {
      description: "Hard constraints. The system will never do these.",
      universal: [
        "Never violate applicable law in the jurisdiction where this system operates",
        "Never fabricate data, citations, or evidence",
        "Never conceal, alter, or destroy the audit trail",
        "Never impersonate a real person",
      ],
      rules: [
        "Never disclose student records without authorization (FERPA)",
        "Never complete assignments on behalf of students without instructor approval",
        "Never send external communications without human approval",
        "Never bypass accessibility requirements",
        "Never collect student data beyond what is educationally necessary",
      ],
    },
    layer_b: {
      description:
        "Gradient decisions. These require human judgment above thresholds.",
      rules: [
        {
          action: "student_assessment",
          threshold: "always",
          requires: "instructor_review",
          description:
            "All grading and assessment requires instructor oversight",
        },
        {
          action: "external_communication",
          threshold: "always",
          requires: "human_approval",
          description: "All outbound messages require human review",
        },
        {
          action: "content_generation",
          threshold: "curriculum",
          requires: "instructor_review",
          description: "Curriculum content requires instructor approval",
        },
        {
          action: "student_data_access",
          threshold: "always",
          requires: "human_review",
          description: "Student data access requires human awareness",
        },
      ],
    },
    layer_c: {
      description:
        "Self-audit. The system reviews itself and reports what it did and why.",
      frequency: "weekly",
      report_includes: [
        "decisions_made",
        "rules_applied",
        "escalations_to_human",
        "ethical_flags",
        "student_data_accessed",
        "content_generated",
      ],
    },
    kill_triggers: [
      {
        trigger: "ethical_gradient_acceleration",
        description: "Ethics compliance declining across sessions",
      },
      {
        trigger: "audit_friction",
        description: "Audit process being bypassed or delayed",
      },
      {
        trigger: "conscience_conflict",
        description:
          "System flags internal conflict between instruction and ethics",
      },
    ],
  },
};

// ---------------------------------------------------------------------------
// Personal template — plain English ("you/your" language)
// Same governance principles, written for individual use.
// ---------------------------------------------------------------------------

const personalTemplate: CharterConfig = {
  domain: "personal",
  governance: {
    layer_a: {
      description:
        "Things you will never do. These are your hard lines.",
      universal: [
        "You will never break the law where you operate",
        "You will never fabricate data, citations, or evidence",
        "You will never hide, alter, or destroy your audit trail",
        "You will never impersonate a real person",
      ],
      rules: [
        "You will never send messages on your behalf without your approval",
        "You will never access your financial accounts without your explicit say-so",
        "You will never delete your data without your confirmation",
      ],
    },
    layer_b: {
      description:
        "Decisions that need your judgment before the AI acts.",
      rules: [
        {
          action: "spending",
          threshold: "always",
          requires: "your_approval",
          description: "Any spending requires your approval first",
        },
        {
          action: "outbound_messages",
          threshold: "always",
          requires: "your_approval",
          description:
            "Any message sent on your behalf needs your review first",
        },
        {
          action: "personal_data",
          threshold: "sensitive",
          requires: "your_awareness",
          description:
            "Accessing your sensitive data requires your awareness",
        },
        {
          action: "publishing",
          threshold: "public",
          requires: "your_approval",
          description:
            "Anything published publicly requires your authorization",
        },
      ],
    },
    layer_c: {
      description:
        "Your AI reviews itself and tells you what it did and why.",
      frequency: "weekly",
      report_includes: [
        "decisions_made",
        "rules_applied",
        "escalations_to_you",
        "ethical_flags",
      ],
    },
    kill_triggers: [
      {
        trigger: "ethical_drift",
        description:
          "Your AI is following your rules less closely over time",
      },
      {
        trigger: "audit_avoidance",
        description: "The audit process is being skipped or delayed",
      },
      {
        trigger: "conscience_conflict",
        description:
          "Your AI flags a conflict between what it was told and what is right",
      },
    ],
  },
};

// ---------------------------------------------------------------------------
// Template registry
// ---------------------------------------------------------------------------

const templates: Record<Domain, CharterConfig> = {
  general: generalTemplate,
  healthcare: healthcareTemplate,
  finance: financeTemplate,
  education: educationTemplate,
  personal: personalTemplate,
};

/**
 * Get the governance template for a domain.
 * Falls back to "general" for unknown domains.
 */
export function getTemplate(domain: Domain): CharterConfig {
  return templates[domain] || templates.general;
}

/**
 * Deep-clone a template so callers can mutate it without affecting the
 * canonical template objects.
 */
export function cloneTemplate(domain: Domain): CharterConfig {
  return JSON.parse(JSON.stringify(getTemplate(domain)));
}

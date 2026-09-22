# Same-As Domain Automation — Simple Overview

*A plain-language guide for the CPT team. No technical knowledge needed.*

---

## 1. The project in one line

A system that takes a long list of company web addresses and automatically works out **which ones belong to the same company**, **which one is the main address**, and **which cases a person still needs to check**.

---

## 2. The problem today

Today CPT often receives a big list of web addresses for companies. Someone has to go through them by hand and figure out whether two addresses are really the same company, which address is the main one, and which are just extra or old addresses. This is slow and tiring, and it is very easy to make mistakes. When the list has **thousands of addresses**, checking every one manually simply isn't practical.

---

## 3. What we are building

A system that does the first, heavy part of this work automatically. CPT will be able to hand it a large list of web addresses, and the system will sort them out and tell CPT:

- which addresses belong to the **same company**,
- which one is the **main (primary) address**,
- which ones are **secondary (extra) addresses**, and
- which cases are **unclear and need a person to look**.

The goal is to save time on the easy, obvious cases so people can focus only on the tricky ones.

---

## 4. How the system will work

The system works through each web address step by step, like a careful person would:

```text
CPT uploads a file of web addresses
        ↓
The system checks the file is readable
        ↓
The system looks at each web address one by one (safely)
        ↓
It gathers simple clues from each one, for example:
   • Does one address send visitors to another address?
   • Does a page point to another address as its "official" one?
   • Do two addresses share the same phone, email, or social page?
   • Do the pages show the same name and the same content?
        ↓
Using these clues, it groups addresses that belong to the same company
        ↓
Within each group, it decides which address is the MAIN one
   (for example, if several addresses all send visitors to one address,
    that one is likely the main address)
        ↓
It labels every address: Main, Secondary, or Needs Review
        ↓
It hands the results back to CPT
```

Every decision is based on **real clues it found**, not on guessing — and it always shows the reasons behind each answer.

---

## 5. What CPT will get as the final output

For every web address in the uploaded list, CPT gets a clear result:

- which **company group** it belongs to,
- whether it is the **Main** address, a **Secondary** address, or **Needs Review**,
- a **confidence level** (how sure the system is), and
- the **reasons** behind the answer (the clues it used).

So instead of a raw list of thousands of addresses, CPT gets an organised, explained result they can trust and act on quickly.

---

## 6. What happens to uncertain cases

The system is built to be **careful, not pushy**. When the clues are weak, missing, or point in different directions, it does **not** force an answer. Instead it marks the case as **"Needs Review"** and shows the reasons why.

This means:

- Clear cases are handled automatically, saving a lot of time.
- Only the genuinely unclear cases come to a person — with the clues already laid out, so the check is quick.

In short: the system does the obvious work automatically and honestly flags anything it isn't sure about, so CPT spends time only where human judgement is really needed.

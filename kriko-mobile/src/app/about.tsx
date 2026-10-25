import Constants from 'expo-constants';
import { router } from 'expo-router';
import { useState } from 'react';
import { Linking, StyleSheet, View } from 'react-native';

import { Divider, HeaderAction, Hero, Page } from '../components/Chrome';
import { BackIcon, GlobeIcon, ShieldIcon, SparkIcon } from '../components/Icon';
import { MotionPressable, MotionView } from '../components/Motion';
import { SectionLabel } from '../components/Primitives';
import { AnimatedDisclosure, DisclosureChevron } from '../components/AnimatedDisclosure';
import { UIARC_LICENSE } from '../theme/licenses';
import { tr } from '../i18n';
import { gap, PAGE_X } from '../theme/tokens';
import { makeStyles, useColors } from '../theme/theme';
import { Txt } from '../theme/Txt';

const REPO = 'https://github.com/Berbadov/kriko';

export default function About() {
  const [licenseOpen, setLicenseOpen] = useState(false);
  const color = useColors();
  const styles = useStyles();
  return (
    <Page
      artHeight={0}
      actions={<HeaderAction label="Back" onPress={() => router.back()}><BackIcon size={21} color={color.ink} /></HeaderAction>}
    >
      <Hero crumb="kriko / about" title="About" subtitle="A local-first reader, with a researcher inside." />

      <View style={styles.body}>
        <MotionView delay={0} style={styles.intro}>
          <Txt variant="monoSm" tone="accent" caps>{tr(`Version ${Constants.expoConfig?.version ?? '0.7.0'} · Friends test`)}</Txt>
          <Txt variant="productTitle" tone="ink">Know what you’re buying.</Txt>
          <Txt variant="body" tone="ink3">
            Ask what is known to go wrong, or read a product listing in front of you. Kriko researches the open web, cites the pages it read, and keeps the work where you can see it.
          </Txt>
        </MotionView>

        <Divider />

        <MotionView delay={80} style={styles.section}>
          <SectionLabel>Made to stay clear</SectionLabel>
          <Point index="01" title="Scan as you browse" body="Tap the floating Kriko button to capture the listing and read findings over the product page." />
          <Point index="02" title="Keep several products moving" body="Queue another scan while research continues. Each result keeps its own sources and conversation." />
          <Point index="03" title="Check the exact store" body="Read comments from the selected site, with an optional product URL and no review substitution." />
          <Point index="04" title="See the work" body="Searches stop when evidence is enough or stops improving, leaving time to write the answer." />
        </MotionView>

        <Divider />

        <MotionView delay={160} style={styles.section}>
          <View style={styles.head}>
            <ShieldIcon size={17} color={color.accent} />
            <SectionLabel>What leaves this phone</SectionLabel>
          </View>
          <Txt variant="bodyTight" tone="ink3" style={styles.bodyCopy}>
            Your question and listing text go to Inception to write the answer. Search queries and chosen URLs go to DeepSeek. Screenshots are uploaded once to DeepSeek vision for reading, then kept only as a thumbnail in the conversation. There is no Kriko account, server, or analytics.
          </Txt>
          <View style={styles.facts}>
            <Fact icon={<SparkIcon size={15} color={color.ink3} />} label="Answers" value="Mercury 3" />
            <Fact icon={<GlobeIcon size={15} color={color.ink3} />} label="Search and pages" value="DeepSeek Search & Fetch" />
            <Fact icon={<ShieldIcon size={15} color={color.ink3} />} label="Image reading" value="DeepSeek vision" />
          </View>
        </MotionView>

        <Divider />

        <View style={styles.section}>
          <MotionPressable onPress={() => setLicenseOpen((value) => !value)}
            accessibilityRole="button" accessibilityLabel={tr('UIArc license')}
            accessibilityState={{ expanded: licenseOpen }} style={styles.link}>
            <View style={styles.linkText}>
              <Txt variant="rowTitle">Motion by UIArc</Txt>
              <Txt variant="bodyTight" tone="ink3">Native adaptation · MIT license</Txt>
            </View>
            <DisclosureChevron open={licenseOpen}><Txt variant="body" tone="ink3">›</Txt></DisclosureChevron>
          </MotionPressable>
          <AnimatedDisclosure open={licenseOpen}>
            <Txt variant="bodyTight" tone="ink3" translate={false}>{UIARC_LICENSE}</Txt>
          </AnimatedDisclosure>
        </View>

        <MotionView delay={240}>
          <MotionPressable
            onPress={() => Linking.openURL(REPO).catch(() => {})}
            accessibilityRole="link"
            accessibilityLabel={tr('Kriko on GitHub')}
            style={styles.link}
          >
            <GlobeIcon size={17} color={color.accent} />
            <View style={styles.linkText}>
              <Txt variant="rowTitle" tone="ink">Open source</Txt>
              <Txt variant="bodyTight" tone="ink3">github.com/Berbadov/kriko</Txt>
            </View>
            <Txt variant="actionSmall" tone="accent">Visit</Txt>
          </MotionPressable>
        </MotionView>

        <Txt variant="monoSm" tone="ink3" style={styles.foot}>
          Mercury and DeepSeek are independent services with their own availability and prices.
        </Txt>
      </View>
    </Page>
  );
}

function Point({ index, title, body }: { index: string; title: string; body: string }) {
  const styles = useStyles();
  return (
    <View style={styles.point}>
      <Txt variant="monoSm" tone="accent" style={styles.number}>{index}</Txt>
      <View style={styles.pointText}>
        <Txt variant="rowTitle" tone="ink">{title}</Txt>
        <Txt variant="bodyTight" tone="ink3">{body}</Txt>
      </View>
    </View>
  );
}

function Fact({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  const styles = useStyles();
  return (
    <View style={styles.fact}>
      {icon}
      <Txt variant="bodyTight" tone="ink3" style={styles.factLabel}>{label}</Txt>
      <Txt variant="meta" tone="ink" style={styles.factValue}>{value}</Txt>
    </View>
  );
}

const useStyles = makeStyles((color) => StyleSheet.create({
  body: { paddingHorizontal: PAGE_X, gap: gap[4], paddingBottom: 44 },
  intro: { gap: gap[3] },
  section: { gap: gap[3] },
  point: { flexDirection: 'row', alignItems: 'flex-start', gap: gap[3] },
  number: { width: 24, paddingTop: 2 },
  pointText: { flex: 1, gap: 3 },
  head: { flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  bodyCopy: { lineHeight: 21 },
  facts: { gap: gap[1], paddingTop: gap[1] },
  fact: { minHeight: 34, flexDirection: 'row', alignItems: 'center', gap: gap[2] },
  factLabel: { flex: 1 },
  factValue: { maxWidth: '60%', textAlign: 'right' },
  link: { minHeight: 56, flexDirection: 'row', alignItems: 'center', gap: gap[3] },
  linkText: { flex: 1, gap: 2 },
  foot: { textAlign: 'center', lineHeight: 17, paddingHorizontal: gap[3], paddingTop: gap[2] },
}));

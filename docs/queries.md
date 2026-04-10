# A8.1 Reasoning Benchmark — Full Query Log
## 500 Direct + 500 CoT + 500 Abductive + 200 Complex = 1,700 Queries
## Seed: 42 | Date: 2026-04-04 20:57:28

---

## Summary

| Mode | Metric | Value |
|------|--------|-------|
| Direct | Hit@1 | 77.2% (386/500) |
| Direct | Hit@5 | 92.6% (463/500) |
| Direct | Time | 1.8s |
| CoT | Hit@5 (after hop 2) | 96.6% (483/500) |
| CoT | Recovered | 20 misses saved |
| CoT | Uplift | +4.0% |
| CoT | Time | 0.3s |
| Abductive | Verified | 0/463 (0.0%) |
| Abductive | Time | 0.3s |
| Complex | Both found | 99.0% (198/200) |
| Complex | One found | 2 |
| Complex | Neither | 0 |
| Complex | Time | 0.4s |

---

## Mode 1 — Direct Queries (500)

| # | Query | Gold Answer | Top Answer | Hit@1 | Hit@5 |
|---|-------|-------------|------------|-------|-------|
| 1 | edward_c._campbell occupation | judge | politician | ✗ | ✓ |
| 2 | y_felinheli instance_of | community | community | ✓ | ✓ |
| 3 | isher_judge_ahluwalia educated_at | massachusetts_institute_o | university_of_calcutta | ✗ | ✓ |
| 4 | foxa1 instance_of | gene | gene | ✓ | ✓ |
| 5 | ardentes shares_border_with | le_poinçonnet | mers-sur-indre | ✗ | ✓ |
| 6 | tristin_mays instance_of | human | human | ✓ | ✓ |
| 7 | héctor_jiménez occupation | film_producer | film_producer | ✓ | ✓ |
| 8 | otonica country | slovenia | slovenia | ✓ | ✓ |
| 9 | popeye genre | action_game | platform_game | ✗ | ✓ |
| 10 | gray_marine_motor_company headquarters_location | detroit | detroit | ✓ | ✓ |
| 11 | shan_vincent_de_paul instance_of | human | human | ✓ | ✓ |
| 12 | the_big_town instance_of | short_film | film | ✗ | ✓ |
| 13 | 1944_cleveland_rams_season sport | american_football | american_football | ✓ | ✓ |
| 14 | falborek located_in_time_zone | utc+01:00 | utc+02:00 | ✗ | ✓ |
| 15 | ernest_champion member_of_sports_team | charlton_athletic_f.c. | charlton_athletic_f.c. | ✓ | ✓ |
| 16 | edward_boustead place_of_birth | yorkshire | yorkshire | ✓ | ✓ |
| 17 | m38_wolfhound instance_of | armored_car | armored_car | ✓ | ✓ |
| 18 | krang present_in_work | teenage_mutant_ninja_turt | teenage_mutant_ninja_turt | ✗ | ✓ |
| 19 | blind_man's_bluff instance_of | film | card_game | ✗ | ✓ |
| 20 | ciini instance_of | taxon | taxon | ✓ | ✓ |
| 21 | shameless country_of_origin | germany | united_states_of_america | ✗ | ✓ |
| 22 | bazar_house_in_miłosław located_in_the_administrative_t | miłosław | miłosław | ✓ | ✓ |
| 23 | bill_bailey given_name | bill | bill | ✓ | ✓ |
| 24 | helene_weber country_of_citizenship | germany | germany | ✓ | ✓ |
| 25 | franz_von_seitz given_name | franz | franz | ✓ | ✓ |
| 26 | hugh_hefner:_playboy,_activist_and_rebel cast_member | jenny_mccarthy | dick_cavett | ✗ | ✓ |
| 27 | george_anderson place_of_death | canada | canada | ✓ | ✓ |
| 28 | laynce_nix handedness | left-handedness | left-handedness | ✓ | ✓ |
| 29 | piano instance_of | play | play | ✓ | ✓ |
| 30 | roman_bagration country_of_citizenship | georgia | georgia | ✓ | ✓ |
| 31 | united_nations_security_council_resolution_551 instance | united_nations_security_c | united_nations_security_c | ✓ | ✓ |
| 32 | gustav_flatow place_of_death | theresienstadt_concentrat | theresienstadt_concentrat | ✓ | ✓ |
| 33 | ron_white occupation | songwriter | actor | ✗ | ✓ |
| 34 | karin_kschwendt country_of_citizenship | austria | austria | ✓ | ✓ |
| 35 | urubamba_mountain_range country | peru | peru | ✓ | ✓ |
| 36 | written_language opposite_of | spoken_language | spoken_language | ✓ | ✓ |
| 37 | stefanowo,_masovian_voivodeship located_in_time_zone | utc+02:00 | utc+02:00 | ✓ | ✓ |
| 38 | choreutis_achyrodes taxon_rank | species | species | ✓ | ✓ |
| 39 | sigeberht instance_of | human | human | ✓ | ✓ |
| 40 | francesco_bracciolini occupation | writer | playwright | ✗ | ✓ |
| 41 | shine,_shine,_my_star genre | grotto-esque | tragicomedy | ✗ | ✓ |
| 42 | premam composer | gopi_sundar | rajesh_murugesan | ✗ | ✓ |
| 43 | honghuli_station instance_of | metro_station | metro_station | ✓ | ✓ |
| 44 | porrera shares_border_with | poboleda | cornudella_de_montsant | ✗ | ✗ |
| 45 | george_r._johnson instance_of | human | human | ✓ | ✓ |
| 46 | ludmilla_of_bohemia spouse | louis_i | louis_i | ✓ | ✓ |
| 47 | canty_bay instance_of | hamlet | hamlet | ✓ | ✓ |
| 48 | halston cause_of_death | cancer | cancer | ✓ | ✓ |
| 49 | hans_wilhelm_frei award_received | john_simon_guggenheim_mem | john_simon_guggenheim_mem | ✓ | ✓ |
| 50 | the_little_thief director | claude_miller | claude_miller | ✓ | ✓ |
| 51 | mydas_luteipennis parent_taxon | mydas | mydas | ✓ | ✓ |
| 52 | tere_glassie instance_of | human | human | ✓ | ✓ |
| 53 | jordi_puigneró_i_ferrer instance_of | human | human | ✓ | ✓ |
| 54 | pedro_colón member_of_political_party | democratic_party | democratic_party | ✓ | ✓ |
| 55 | schnals located_in_time_zone | utc+01:00 | utc+01:00 | ✓ | ✓ |
| 56 | human_resources_university instance_of | university | university | ✓ | ✓ |
| 57 | general_post_office located_in_the_administrative_terri | queensland | dublin | ✗ | ✓ |
| 58 | euphemia_of_rügen instance_of | human | human | ✓ | ✓ |
| 59 | antikensammlung_berlin instance_of | art_collection | art_collection | ✓ | ✓ |
| 60 | château_de_cléron located_in_the_administrative_territo | cléron | cléron | ✓ | ✓ |
| 61 | rescue_nunatak instance_of | mountain | mountain | ✓ | ✓ |
| 62 | vukašin_jovanović member_of_sports_team | serbia_national_under-19_ | serbia_national_under-19_ | ✓ | ✓ |
| 63 | my_losing_season publisher | nan_a._talese | nan_a._talese | ✓ | ✓ |
| 64 | australian_derby country | australia | australia | ✓ | ✓ |
| 65 | helmut_kremers member_of_sports_team | germany_national_football | memphis_rogues | ✗ | ✓ |
| 66 | alyaksandr_alhavik member_of_sports_team | fc_khimik_svetlogorsk | fc_smorgon | ✗ | ✓ |
| 67 | gornje_gare located_in_time_zone | utc+01:00 | utc+01:00 | ✓ | ✓ |
| 68 | canton_of_jarnages contains_administrative_territorial_ | saint-silvain-sous-toulx | parsac | ✗ | ✗ |
| 69 | 1983_virginia_slims_of_washington_–_singles winner | martina_navratilova | martina_navratilova | ✓ | ✓ |
| 70 | ross_bentley country_of_citizenship | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 71 | neuroscientist field_of_this_occupation | neuroscience | neuroscience | ✓ | ✓ |
| 72 | sucha_struga located_in_time_zone | utc+01:00 | utc+02:00 | ✗ | ✓ |
| 73 | beauty_and_the_beast significant_event | première | première | ✓ | ✓ |
| 74 | wilkins_highway country | australia | australia | ✓ | ✓ |
| 75 | girl_in_the_cadillac cast_member | william_shockley | erika_eleniak | ✗ | ✗ |
| 76 | jeziorki,_świecie_county located_in_the_administrative_ | gmina_lniano | gmina_lniano | ✓ | ✓ |
| 77 | kaitō_royale country_of_origin | japan | japan | ✓ | ✓ |
| 78 | fayette_high_school located_in_the_administrative_terri | ohio | ohio | ✓ | ✓ |
| 79 | brice_dja_djédjé member_of_sports_team | olympique_de_marseille | olympique_de_marseille | ✓ | ✓ |
| 80 | dhunni instance_of | union_council_of_pakistan | union_council_of_pakistan | ✓ | ✓ |
| 81 | 1991_asian_women's_handball_championship instance_of | asian_women's_handball_ch | asian_women's_handball_ch | ✓ | ✓ |
| 82 | the_lost_take record_label | anticon. | anticon. | ✓ | ✓ |
| 83 | curtner country | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 84 | chemical_heart part_of | new_detention | new_detention | ✓ | ✓ |
| 85 | dermacentor_circumguttatus taxon_rank | species | species | ✓ | ✓ |
| 86 | daniel_avery place_of_birth | groton | groton | ✓ | ✓ |
| 87 | mansfield located_in_the_administrative_territorial_ent | desoto_parish | parke_county | ✗ | ✗ |
| 88 | clinton_solomon instance_of | human | human | ✓ | ✓ |
| 89 | the_evolution_of_gospel performer | sounds_of_blackness | sounds_of_blackness | ✓ | ✓ |
| 90 | joel_feeney place_of_birth | oakville | oakville | ✓ | ✓ |
| 91 | shareef_adnan member_of_sports_team | shabab_al-ordon_club | palestine_national_footba | ✗ | ✓ |
| 92 | shadiwal_hydropower_plant instance_of | hydroelectric_power_stati | hydroelectric_power_stati | ✓ | ✓ |
| 93 | national_cycle_route_75 instance_of | long-distance_cycling_rou | long-distance_cycling_rou | ✓ | ✓ |
| 94 | det_gælder_os_alle genre | drama_film | drama_film | ✓ | ✓ |
| 95 | upplanda located_in_time_zone | utc+02:00 | utc+02:00 | ✓ | ✓ |
| 96 | south_pasadena_unified_school_district located_in_the_a | california | california | ✓ | ✓ |
| 97 | karl_brunner given_name | karl | karl | ✓ | ✓ |
| 98 | rehoboth_ratepayers'_association headquarters_location | rehoboth | rehoboth | ✓ | ✓ |
| 99 | 2012_thai_division_1_league sports_season_of_league_or_ | thai_division_1_league | thai_division_1_league | ✓ | ✓ |
| 100 | georges_semichon given_name | george | george | ✓ | ✓ |
| 101 | baphia_puguensis iucn_conservation_status | endangered_species | endangered_species | ✓ | ✓ |
| 102 | al_son_de_la_marimba cast_member | sara_garcía | sara_garcía | ✓ | ✓ |
| 103 | cary_brothers country_of_citizenship | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 104 | thomas_fitzgibbon_moore instance_of | human | human | ✓ | ✓ |
| 105 | anthony_cooke given_name | anthony | anthony | ✓ | ✓ |
| 106 | richard_williams educated_at | mississippi_state_univers | northern_secondary_school | ✗ | ✓ |
| 107 | simone_le_bargy occupation | actor | actor | ✓ | ✓ |
| 108 | avengers:_infinity_war cast_member | paul_bettany | scarlett_johansson | ✗ | ✗ |
| 109 | antipas_of_pergamum country_of_citizenship | ancient_rome | ancient_rome | ✓ | ✓ |
| 110 | between_friends cast_member | lou_tellegen | michael_parks | ✗ | ✓ |
| 111 | the_age_of_adaline cast_member | harrison_ford | blake_lively | ✗ | ✗ |
| 112 | list_of_first_ladies_of_cameroon is_a_list_of | person | person | ✓ | ✓ |
| 113 | auzeville-tolosane shares_border_with | pechbusque | ramonville-saint-agne | ✗ | ✓ |
| 114 | eudonia_australialis parent_taxon | eudonia | eudonia | ✓ | ✓ |
| 115 | cass_building architect | smithgroup | smithgroup | ✓ | ✓ |
| 116 | jan_kmenta employer | university_of_michigan | university_of_michigan | ✓ | ✓ |
| 117 | paul_freeman educated_at | eastman_school_of_music | eastman_school_of_music | ✓ | ✓ |
| 118 | karin_söder instance_of | human | human | ✓ | ✓ |
| 119 | the_mice cast_member | henry_silva | henry_silva | ✓ | ✓ |
| 120 | tomás_herrera_martínez participant_of | 1972_summer_olympics | 1976_summer_olympics | ✗ | ✓ |
| 121 | james_pritchard instance_of | human | human | ✓ | ✓ |
| 122 | 1280_in_poetry facet_of | poetry | poetry | ✓ | ✓ |
| 123 | somatina_accraria instance_of | taxon | taxon | ✓ | ✓ |
| 124 | paul_massey instance_of | human | human | ✓ | ✓ |
| 125 | pyrausta_sanguinalis taxon_rank | species | species | ✓ | ✓ |
| 126 | snuggle_truck game_mode | single-player_video_game | single-player_video_game | ✓ | ✓ |
| 127 | frederick_fitzclarence given_name | frederick | frederick | ✓ | ✓ |
| 128 | michael_cartellone instrument | drum_kit | drum_kit | ✓ | ✓ |
| 129 | niphoparmena_latifrons parent_taxon | niphoparmena | niphoparmena | ✓ | ✓ |
| 130 | cité_du_niger country | mali | mali | ✓ | ✓ |
| 131 | tsarevich_dmitry_alexeyevich_of_russia sibling | sophia_alekseyevna_of_rus | tsarevna_natalya_alexeevn | ✗ | ✗ |
| 132 | dancing_in_water cast_member | petar_banićević | ružica_sokić | ✗ | ✗ |
| 133 | echunga country | australia | australia | ✓ | ✓ |
| 134 | nesoptilotis instance_of | taxon | taxon | ✓ | ✓ |
| 135 | maximilian,_crown_prince_of_saxony sibling | princess_maria_amalia_of_ | princess_maria_josepha_of | ✗ | ✓ |
| 136 | 2013_tatarstan_open_–_doubles sport | tennis | tennis | ✓ | ✓ |
| 137 | the_day_of_the_owl language_of_work_or_name | italian | italian | ✓ | ✓ |
| 138 | catch_me_if_you_can instance_of | album | (none) | ✗ | ✗ |
| 139 | oleszki located_in_the_administrative_territorial_entit | gmina_busko-zdrój | gmina_busko-zdrój | ✓ | ✓ |
| 140 | johann_christian_von_stramberg occupation | historian | historian | ✓ | ✓ |
| 141 | denis_kapochkin member_of_sports_team | fc_nara-shbfr_naro-fomins | fc_moscow | ✗ | ✓ |
| 142 | brad_isbister instance_of | human | human | ✓ | ✓ |
| 143 | phaethontidae parent_taxon | phaethontiformes | phaethontiformes | ✓ | ✓ |
| 144 | the_house_of_the_seven_gables production_designer | jack_otterson | jack_otterson | ✓ | ✓ |
| 145 | dean_of_ferns instance_of | wikimedia_list_article | wikimedia_list_article | ✓ | ✓ |
| 146 | propilidium_pertenue taxon_rank | species | species | ✓ | ✓ |
| 147 | br.1050_alizé armament | depth_charge | aerial_torpedo | ✗ | ✓ |
| 148 | olbrachcice,_masovian_voivodeship located_in_time_zone | utc+02:00 | utc+01:00 | ✗ | ✓ |
| 149 | gega_diasamidze occupation | association_football_play | association_football_play | ✓ | ✓ |
| 150 | patinoire_de_malley owned_by | prilly | prilly | ✓ | ✓ |
| 151 | aleksey_petrovich_yermolov conflict | napoleonic_wars | napoleonic_wars | ✓ | ✓ |
| 152 | i_hate_you_now... genre | pop_music | pop_music | ✓ | ✓ |
| 153 | nanda_devi_national_park heritage_designation | unesco_world_heritage_sit | unesco_world_heritage_sit | ✓ | ✓ |
| 154 | buldhana_vidhan_sabha_constituency country | india | india | ✓ | ✓ |
| 155 | camden_airstrip instance_of | airport | airport | ✓ | ✓ |
| 156 | university_of_california,_irvine has_part | school_of_education | university_of_california, | ✗ | ✗ |
| 157 | mühlanger country | germany | germany | ✓ | ✓ |
| 158 | ștefan_cel_mare located_in_the_administrative_territori | neamț_county | vaslui_county | ✗ | ✓ |
| 159 | michael_f._guyer instance_of | human | human | ✓ | ✓ |
| 160 | volume_1:_65's.late.nite.double-a-side.college.cut-up.t | album | album | ✓ | ✓ |
| 161 | far_cry producer | nick_raskulinecz | wolfgang_herold | ✗ | ✓ |
| 162 | pilocrocis_cuprescens parent_taxon | pilocrocis | pilocrocis | ✓ | ✓ |
| 163 | hughie_dow member_of_sports_team | sunderland_a.f.c. | easington_colliery_a.f.c. | ✗ | ✓ |
| 164 | adalbert_iii_of_saxony sibling | margaret_of_saxony,_duche | john,_elector_of_saxony | ✗ | ✓ |
| 165 | george_herbert,_8th_earl_of_carnarvon educated_at | eton_college | eton_college | ✓ | ✓ |
| 166 | benjamin_heywood languages_spoken,_written_or_signed | english | english | ✓ | ✓ |
| 167 | tashkent_mechanical_plant instance_of | business | business | ✓ | ✓ |
| 168 | jealous record_label | parlophone | island_records | ✗ | ✓ |
| 169 | valentin_bădoi position_played_on_team | midfielder | midfielder | ✓ | ✓ |
| 170 | bright_lights:_starring_carrie_fisher_and_debbie_reynol | debbie_reynolds | debbie_reynolds | ✓ | ✓ |
| 171 | ace_of_aces producer | horst_wendlandt | horst_wendlandt | ✓ | ✓ |
| 172 | gennaro_fragiello member_of_sports_team | a.c._carpenedolo | bologna_f.c._1909 | ✗ | ✗ |
| 173 | tiago_jonas place_of_birth | porto | porto | ✓ | ✓ |
| 174 | le_lyrial instance_of | cruise_ship | cruise_ship | ✓ | ✓ |
| 175 | knut_johannesen country_of_citizenship | norway | norway | ✓ | ✓ |
| 176 | marco_airosa member_of_sports_team | angola_national_football_ | g.d.p._costa_de_caparica | ✗ | ✗ |
| 177 | james_vasquez instance_of | human | human | ✓ | ✓ |
| 178 | kaklamanis writing_system | greek_alphabet | greek_alphabet | ✓ | ✓ |
| 179 | harold_huntley_bassett occupation | military_officer | military_officer | ✓ | ✓ |
| 180 | red_rock_bridge instance_of | bridge | bridge | ✓ | ✓ |
| 181 | sebastian_praus languages_spoken,_written_or_signed | german | german | ✓ | ✓ |
| 182 | franjo_džidić member_of_sports_team | nk_široki_brijeg | hnk_čapljina | ✗ | ✓ |
| 183 | margherita_d'anjou librettist | felice_romani | felice_romani | ✓ | ✓ |
| 184 | villa_melnik_winery headquarters_location | harsovo,_blagoevgrad_prov | harsovo,_blagoevgrad_prov | ✓ | ✓ |
| 185 | jamie_rauch place_of_birth | houston | houston | ✓ | ✓ |
| 186 | pekka_sylvander participant_of | 1964_summer_olympics | 1964_summer_olympics | ✓ | ✓ |
| 187 | female_agents cast_member | xavier_beauvois | xavier_beauvois | ✓ | ✓ |
| 188 | yvelines contains_administrative_territorial_entity | le_mesnil-le-roi | cernay-la-ville | ✗ | ✗ |
| 189 | vince_clarke bowling_style | leg_break | leg_break | ✓ | ✓ |
| 190 | ashley_graham country_of_citizenship | australia | united_states_of_america | ✗ | ✓ |
| 191 | dreams_awake country_of_origin | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 192 | sharove country | albania | albania | ✓ | ✓ |
| 193 | men_without_a_fatherland cast_member | willi_schaeffers | willy_birgel | ✗ | ✗ |
| 194 | israel_national_basketball_team instance_of | national_sports_team | national_sports_team | ✓ | ✓ |
| 195 | françois-louis_français described_by_source | brockhaus_and_efron_encyc | brockhaus_and_efron_encyc | ✓ | ✓ |
| 196 | kabile_island instance_of | island | island | ✓ | ✓ |
| 197 | conceptual_party_unity political_ideology | stalinism | stalinism | ✓ | ✓ |
| 198 | davy_schollen member_of_sports_team | k.r.c._genk | r.s.c._anderlecht | ✗ | ✓ |
| 199 | robot_entertainment country | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 200 | armands_zeiberliņš member_of_sports_team | ope_if | latvia_national_football_ | ✗ | ✗ |
| 201 | carl_jung significant_person | sigmund_freud | sigmund_freud | ✓ | ✓ |
| 202 | red-shouldered_vanga parent_taxon | calicalicus | calicalicus | ✓ | ✓ |
| 203 | the_secret_war country_of_origin | united_kingdom | united_kingdom | ✓ | ✓ |
| 204 | liebfrauen,_frankfurt located_in_the_administrative_ter | frankfurt | altstadt | ✗ | ✓ |
| 205 | choi_min-ho given_name | min-ho | min-ho | ✓ | ✓ |
| 206 | 1999_segunda_división_peruana instance_of | sports_season | sports_season | ✓ | ✓ |
| 207 | extra_space_storage headquarters_location | cottonwood_heights | cottonwood_heights | ✓ | ✓ |
| 208 | noel_hunt position_played_on_team | forward | forward | ✓ | ✓ |
| 209 | kalmakanda_upazila country | bangladesh | bangladesh | ✓ | ✓ |
| 210 | baillif shares_border_with | basse-terre | vieux-habitants | ✗ | ✓ |
| 211 | rayappanur country | india | india | ✓ | ✓ |
| 212 | haute-marne contains_administrative_territorial_entity | vaudrémont | vroncourt-la-côte | ✗ | ✗ |
| 213 | carlos_turrubiates position_played_on_team | defender | defender | ✓ | ✓ |
| 214 | nevin_william_hayes instance_of | human | human | ✓ | ✓ |
| 215 | john_gillespie member_of_sports_team | scotland_national_rugby_u | british_&_irish_lions | ✗ | ✓ |
| 216 | john_george_walker place_of_birth | jefferson_city | jefferson_city | ✓ | ✓ |
| 217 | maumee-class_oiler followed_by | usns_american_explorer | usns_american_explorer | ✓ | ✓ |
| 218 | vullnet_basha member_of_sports_team | grasshopper_club_zürich | switzerland_national_unde | ✗ | ✓ |
| 219 | ray_ozzie educated_at | university_of_illinois_sy | university_of_illinois_at | ✗ | ✓ |
| 220 | katharine_ross spouse | sam_elliott | conrad_hall | ✗ | ✓ |
| 221 | sringaram cast_member | aditi_rao_hydari | aditi_rao_hydari | ✓ | ✓ |
| 222 | pacific_leaping_blenny parent_taxon | alticus | alticus | ✓ | ✓ |
| 223 | shake_your_rump followed_by | johnny_ryall | johnny_ryall | ✓ | ✓ |
| 224 | jenny_valentine educated_at | goldsmiths,_university_of | goldsmiths,_university_of | ✓ | ✓ |
| 225 | siddharth_gupta instance_of | human | human | ✓ | ✓ |
| 226 | 1990–91_leicester_city_f.c._season sport | association_football | association_football | ✓ | ✓ |
| 227 | sailors'_snug_harbor part_of | new_york_city_subway | new_york_city_subway | ✓ | ✓ |
| 228 | the_foreman_of_the_jury cast_member | roscoe_arbuckle | roscoe_arbuckle | ✓ | ✓ |
| 229 | anno_2205 instance_of | video_game | video_game | ✓ | ✓ |
| 230 | private_confessions cast_member | hans_alfredson | kristina_adolphson | ✗ | ✗ |
| 231 | boy_trouble color | black-and-white | black-and-white | ✓ | ✓ |
| 232 | chester_ray_benjamin educated_at | university_of_iowa | university_of_iowa | ✓ | ✓ |
| 233 | creature instance_of | studio_album | film | ✗ | ✗ |
| 234 | angus_maclaine instance_of | human | human | ✓ | ✓ |
| 235 | the_slammin'_salmon cast_member | cobie_smulders | vivica_a._fox | ✗ | ✗ |
| 236 | i'm_going_home_to_dixie instance_of | song | song | ✓ | ✓ |
| 237 | archinform instance_of | encyclopedia | database | ✗ | ✓ |
| 238 | carry_on..._up_the_khyber country_of_origin | united_kingdom | united_kingdom | ✓ | ✓ |
| 239 | king_abdullah_design_and_development_bureau headquarter | amman | amman | ✓ | ✓ |
| 240 | dorfstetten located_in_time_zone | utc+02:00 | utc+02:00 | ✓ | ✓ |
| 241 | universitas_psychologica publisher | pontifical_xavierian_univ | pontifical_xavierian_univ | ✓ | ✓ |
| 242 | yevhen_drahunov place_of_birth | makiivka | makiivka | ✓ | ✓ |
| 243 | julius_caesar award_received | golden_leopard | golden_leopard | ✓ | ✓ |
| 244 | andrei_sidorenkov member_of_sports_team | viljandi_jk_tulevik | estonia_national_football | ✗ | ✗ |
| 245 | bob_perry member_of_sports_team | fall_river_marksmen | new_bedford_whalers | ✗ | ✓ |
| 246 | mitch_glazer spouse | kelly_lynch | wendie_malick | ✗ | ✓ |
| 247 | amirabad,_faruj country | iran | iran | ✓ | ✓ |
| 248 | são_mamede country | portugal | portugal | ✓ | ✓ |
| 249 | holley_central_school_district located_in_the_administr | new_york | new_york | ✓ | ✓ |
| 250 | es_migjorn_gran located_in_or_next_to_body_of_water | mediterranean_sea | mediterranean_sea | ✓ | ✓ |
| 251 | baby_blue_marine director | john_d._hancock | john_d._hancock | ✓ | ✓ |
| 252 | aeromonas_fluvialis parent_taxon | aeromonas | aeromonas | ✓ | ✓ |
| 253 | bhairava_dweepam country_of_origin | india | india | ✓ | ✓ |
| 254 | leon_mettam instance_of | human | human | ✓ | ✓ |
| 255 | dean_collis country_of_citizenship | australia | australia | ✓ | ✓ |
| 256 | list_of_libraries_in_the_palestinian_territories subcla | list_of_libraries_by_coun | list_of_libraries_by_coun | ✓ | ✓ |
| 257 | now_that's_what_i_call_music!_52 record_label | virgin_records | (none) | ✗ | ✗ |
| 258 | heine_meine country_of_citizenship | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 259 | epacris_calvertiana taxon_rank | species | species | ✓ | ✓ |
| 260 | valea_neagră_river country | romania | romania | ✓ | ✓ |
| 261 | kwns located_in_the_administrative_territorial_entity | texas | texas | ✓ | ✓ |
| 262 | north_african_ostrich taxon_rank | subspecies | subspecies | ✓ | ✓ |
| 263 | rex_hudson country_of_citizenship | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 264 | świerzowa_polska located_in_time_zone | utc+01:00 | utc+01:00 | ✓ | ✓ |
| 265 | besalampy_airport instance_of | airport | airport | ✓ | ✓ |
| 266 | flag_of_rwanda color | blue | yellow | ✗ | ✓ |
| 267 | mark_robinson place_of_birth | belfast | kingston_upon_hull | ✗ | ✗ |
| 268 | james_gamble member_of_political_party | democratic_party | democratic_party | ✓ | ✓ |
| 269 | simone_assemani place_of_death | padua | padua | ✓ | ✓ |
| 270 | tunde_ke_kabab country_of_origin | india | india | ✓ | ✓ |
| 271 | kunihiro_hasegawa given_name | kunihiro | kunihiro | ✓ | ✓ |
| 272 | st_nectan's_church,_hartland named_after | nectan_of_hartland | nectan_of_hartland | ✓ | ✓ |
| 273 | 2017_open_bnp_paribas_banque_de_bretagne_–_singles spor | tennis | tennis | ✓ | ✓ |
| 274 | bathytoma_murdochi instance_of | taxon | taxon | ✓ | ✓ |
| 275 | princess_lalla_meryem_of_morocco sibling | hasna_of_morocco | moulay_rachid_ben_al_hass | ✗ | ✓ |
| 276 | tyne_valley-linkletter located_in_the_administrative_te | prince_edward_island | prince_edward_island | ✓ | ✓ |
| 277 | aretas_akers-douglas,_2nd_viscount_chilston place_of_de | kent | kent | ✓ | ✓ |
| 278 | agua_mala part_of | the_x-files,_season_6 | the_x-files,_season_6 | ✓ | ✓ |
| 279 | jean_thomas_guillaume_lorge place_of_death | chauconin-neufmontiers | chauconin-neufmontiers | ✓ | ✓ |
| 280 | irmgard_griss occupation | politician | jurist | ✗ | ✓ |
| 281 | guynesomia instance_of | taxon | taxon | ✓ | ✓ |
| 282 | sun_longjiang participant_of | 2010_winter_olympics | 2010_winter_olympics | ✓ | ✓ |
| 283 | keena_turner country_of_citizenship | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 284 | fiery-capped_manakin taxon_rank | species | species | ✓ | ✓ |
| 285 | hyatt_place_waikiki_beach country | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 286 | johann_gotthard_von_müller instance_of | human | human | ✓ | ✓ |
| 287 | czechoslovakia head_of_state | václav_havel | tomáš_garrigue_masaryk | ✗ | ✓ |
| 288 | heinrich_nickel country_of_citizenship | germany | germany | ✓ | ✓ |
| 289 | beyond_the_law cast_member | charlie_sheen | ann_smyrner | ✗ | ✓ |
| 290 | placogobio parent_taxon | cyprinidae | cyprinidae | ✓ | ✓ |
| 291 | somerville_college part_of | university_of_oxford | university_of_oxford | ✓ | ✓ |
| 292 | il_profeta cast_member | liana_orfei | vittorio_gassman | ✗ | ✓ |
| 293 | jhouwa_guthi located_in_time_zone | utc+05:45 | utc+05:45 | ✓ | ✓ |
| 294 | death_in_five_boxes country_of_origin | united_kingdom | united_kingdom | ✓ | ✓ |
| 295 | art_schwind place_of_death | sullivan | sullivan | ✓ | ✓ |
| 296 | kurt_ploeger given_name | kurt | kurt | ✓ | ✓ |
| 297 | pleven_province contains_administrative_territorial_ent | pleven_municipality | knezha_municipality | ✗ | ✗ |
| 298 | paddy_mclaughlin member_of_sports_team | harrogate_town_a.f.c. | grimsby_town_f.c. | ✗ | ✓ |
| 299 | ché_ahn country_of_citizenship | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 300 | wolfgang_wolf member_of_sports_team | stuttgarter_kickers | vfr_mannheim | ✗ | ✓ |
| 301 | stand_tall cast_member | arnold_schwarzenegger | arnold_schwarzenegger | ✓ | ✓ |
| 302 | splendrillia_woodringi taxon_rank | species | species | ✓ | ✓ |
| 303 | sutton_hall architect | cass_gilbert | cass_gilbert | ✓ | ✓ |
| 304 | control cast_member | michelle_rodriguez | craig_parkinson | ✗ | ✗ |
| 305 | danièle_sallenave occupation | journalist | journalist | ✓ | ✓ |
| 306 | kieron_barry instance_of | human | human | ✓ | ✓ |
| 307 | paulo_césar_arruda_parente member_of_sports_team | fluminense_f.c. | clube_de_regatas_do_flame | ✗ | ✓ |
| 308 | lucas_thwala member_of_sports_team | supersport_united_f.c. | south_africa_national_foo | ✗ | ✓ |
| 309 | frank_killam instance_of | human | human | ✓ | ✓ |
| 310 | encore..._for_future_generations language_of_work_or_na | english | english | ✓ | ✓ |
| 311 | luke_sikma country_of_citizenship | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 312 | joel_carroll participant_of | 2012_summer_olympics | 2012_summer_olympics | ✓ | ✓ |
| 313 | ottmar_edenhofer occupation | economist | economist | ✓ | ✓ |
| 314 | new_riegel_high_school instance_of | state_school | high_school | ✗ | ✓ |
| 315 | david_sánchez_parrilla place_of_birth | tarragona | tarragona | ✓ | ✓ |
| 316 | patrick_zelbel country_of_citizenship | germany | germany | ✓ | ✓ |
| 317 | andrés_roa instance_of | human | human | ✓ | ✓ |
| 318 | insurial instance_of | business | business | ✓ | ✓ |
| 319 | john_holmstrom occupation | cartoonist | writer | ✗ | ✓ |
| 320 | neola_semiaurata taxon_rank | species | species | ✓ | ✓ |
| 321 | kufra instance_of | oasis | impact_crater | ✗ | ✓ |
| 322 | cecily_mary_wise_pickerill occupation | surgeon | surgeon | ✓ | ✓ |
| 323 | john_treacher instance_of | human | human | ✓ | ✓ |
| 324 | thomas_a._swayze,_jr. place_of_birth | tacoma | tacoma | ✓ | ✓ |
| 325 | nuclear_weapons_convention instance_of | treaty | treaty | ✓ | ✓ |
| 326 | jamil_azzaoui given_name | jamil | jamil | ✓ | ✓ |
| 327 | rgs11 chromosome | human_chromosome_16 | human_chromosome_16 | ✓ | ✓ |
| 328 | seo_district instance_of | district_of_south_korea | district_of_south_korea | ✓ | ✓ |
| 329 | belarus–russia_border country | belarus | russia | ✗ | ✓ |
| 330 | les_carter instance_of | human | human | ✓ | ✓ |
| 331 | time shares_border_with | hå | hå | ✓ | ✓ |
| 332 | priseltsi,_varna_province located_in_time_zone | utc+02:00 | utc+02:00 | ✓ | ✓ |
| 333 | confessions_of_an_english_opium-eater language_of_work_ | english | english | ✓ | ✓ |
| 334 | claude_delay given_name | claude | claude | ✓ | ✓ |
| 335 | fis_ski-flying_world_championships_1977 sport | ski_jumping | ski_jumping | ✓ | ✓ |
| 336 | trudy_silver instance_of | human | human | ✓ | ✓ |
| 337 | victor_lustig instance_of | human | human | ✓ | ✓ |
| 338 | oscar_fernández participant_of | 1996_summer_olympics | 1988_summer_olympics | ✗ | ✓ |
| 339 | george_p._fletcher country_of_citizenship | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 340 | william_howard_taft employer | yale_law_school | yale_law_school | ✓ | ✓ |
| 341 | william_cullen,_baron_cullen_of_whitekirk educated_at | university_of_edinburgh | university_of_st_andrews | ✗ | ✓ |
| 342 | kenni_fisilau member_of_sports_team | plymouth_albion_r.f.c. | plymouth_albion_r.f.c. | ✓ | ✓ |
| 343 | yasmine_pahlavi country_of_citizenship | iran | iran | ✓ | ✓ |
| 344 | rodnay_zaks field_of_work | computer_science | computer_science | ✓ | ✓ |
| 345 | ben_cauchi occupation | photographer | photographer | ✓ | ✓ |
| 346 | 2015_afghan_premier_league instance_of | sports_season | sports_season | ✓ | ✓ |
| 347 | monark_starstalker from_fictional_universe | marvel_universe | marvel_universe | ✓ | ✓ |
| 348 | bernhard_von_langenbeck given_name | bernhard | bernhard | ✓ | ✓ |
| 349 | tony_denman instance_of | human | human | ✓ | ✓ |
| 350 | niels_helveg_petersen position_held | minister_of_economic_and_ | minister_of_economic_and_ | ✓ | ✓ |
| 351 | petite_formation instance_of | formation | formation | ✓ | ✓ |
| 352 | la_odalisca_no._13 country_of_origin | mexico | mexico | ✓ | ✓ |
| 353 | who's_harry_crumb? genre | comedy_film | comedy_film | ✓ | ✓ |
| 354 | olympiakos_nicosia_fc participant_of | 1951–52_cypriot_first_div | 1967–68_greek_cup | ✗ | ✗ |
| 355 | deep_thought sport | chess | chess | ✓ | ✓ |
| 356 | reginald_wynn_owen instance_of | human | human | ✓ | ✓ |
| 357 | bill_white member_of_sports_team | newport_county_a.f.c. | philadelphia_phillies | ✗ | ✗ |
| 358 | burmese_american instance_of | ethnic_group | ethnic_group | ✓ | ✓ |
| 359 | university_of_calgary_faculty_of_arts located_in_the_ad | calgary | calgary | ✓ | ✓ |
| 360 | smarcc1 found_in_taxon | homo_sapiens | homo_sapiens | ✓ | ✓ |
| 361 | dermival_almeida_lima member_of_sports_team | brasiliense_futebol_clube | rubin_kazan | ✗ | ✗ |
| 362 | megachile_digna instance_of | taxon | taxon | ✓ | ✓ |
| 363 | grzegorz_tkaczyk member_of_sports_team | pge_vive_kielce | pge_vive_kielce | ✓ | ✓ |
| 364 | a-1_pictures instance_of | animation_studio | animation_studio | ✓ | ✓ |
| 365 | ipoh country | malaysia | malaysia | ✓ | ✓ |
| 366 | kees_van_ierssel instance_of | human | human | ✓ | ✓ |
| 367 | il_gatto cast_member | mariangela_melato | dalila_di_lazzaro | ✗ | ✗ |
| 368 | tentax_bruneii taxon_rank | species | species | ✓ | ✓ |
| 369 | poison_ivy country_of_origin | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 370 | oktyabr' country | kyrgyzstan | kyrgyzstan | ✓ | ✓ |
| 371 | uss_darke country | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 372 | vincent_moscaritolo occupation | engineer | engineer | ✓ | ✓ |
| 373 | 20_dakika original_language_of_film_or_tv_show | turkish | turkish | ✓ | ✓ |
| 374 | city_of_tiny_lights distributor | icon_productions | icon_productions | ✓ | ✓ |
| 375 | elkin_blanco occupation | association_football_play | association_football_play | ✓ | ✓ |
| 376 | steve_adams member_of_sports_team | swindon_town_f.c. | denaby_united_f.c. | ✗ | ✗ |
| 377 | billy_bibby_&_the_wry_smiles genre | rock_music | rock_music | ✓ | ✓ |
| 378 | the_famous_jett_jackson cast_member | ryan_sommers_baum | lee_thompson_young | ✗ | ✓ |
| 379 | hans_rudi_erdt instance_of | human | human | ✓ | ✓ |
| 380 | küttigen country | switzerland | switzerland | ✓ | ✓ |
| 381 | mindanao_miniature_babbler iucn_conservation_status | data_deficient | data_deficient | ✓ | ✓ |
| 382 | disappear producer | howard_benson | howard_benson | ✓ | ✓ |
| 383 | the_winding_stair cast_member | alma_rubens | alma_rubens | ✓ | ✓ |
| 384 | john_boorman instance_of | human | human | ✓ | ✓ |
| 385 | yankee_in_oz follows | merry_go_round_in_oz | merry_go_round_in_oz | ✓ | ✓ |
| 386 | 1830_united_kingdom_general_election follows | 1826_united_kingdom_gener | 1826_united_kingdom_gener | ✓ | ✓ |
| 387 | makita_ka_lang_muli original_language_of_film_or_tv_sho | filipino | filipino | ✓ | ✓ |
| 388 | burton_latimer twinned_administrative_body | castelnuovo_magra | castelnuovo_magra | ✓ | ✓ |
| 389 | matt_darey record_label | armada_music | armada_music | ✓ | ✓ |
| 390 | jamy,_lublin_voivodeship located_in_time_zone | utc+01:00 | utc+02:00 | ✗ | ✓ |
| 391 | sir_robert_ferguson,_2nd_baronet languages_spoken,_writ | english | english | ✓ | ✓ |
| 392 | eynhallow located_in_or_next_to_body_of_water | atlantic_ocean | atlantic_ocean | ✓ | ✓ |
| 393 | powersite country | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 394 | side_arms_hyper_dyne genre | shoot_'em_up | shoot_'em_up | ✓ | ✓ |
| 395 | radu_i_of_wallachia spouse | kalinikia | kalinikia | ✓ | ✓ |
| 396 | mundi country | india | india | ✓ | ✓ |
| 397 | bccip chromosome | human_chromosome_10 | human_chromosome_10 | ✓ | ✓ |
| 398 | namibia:_the_struggle_for_liberation genre | war_film | documentary_film | ✗ | ✓ |
| 399 | the_narrow_road_to_the_deep_north author | richard_flanagan | richard_flanagan | ✓ | ✓ |
| 400 | pittosporum_dasycaulon taxon_rank | species | species | ✓ | ✓ |
| 401 | dean_stokes member_of_sports_team | armitage_90_f.c. | halesowen_town_f.c. | ✗ | ✓ |
| 402 | odawara located_in_time_zone | utc+09:00 | utc+09:00 | ✓ | ✓ |
| 403 | movement_of_the_national_left instance_of | political_party | political_party | ✓ | ✓ |
| 404 | zen_in_the_united_states subclass_of | buddhism_in_the_united_st | buddhism_in_the_united_st | ✓ | ✓ |
| 405 | alex_whittle member_of_sports_team | liverpool_f.c. | dunfermline_athletic_f.c. | ✗ | ✓ |
| 406 | crossings follows | little_things | mwandishi | ✗ | ✓ |
| 407 | kimberly_buys place_of_birth | sint-niklaas | sint-niklaas | ✓ | ✓ |
| 408 | emoción,_canto_y_guitarra performer | jorge_cafrune | jorge_cafrune | ✓ | ✓ |
| 409 | william_t._martin allegiance | confederate_states_of_ame | confederate_states_of_ame | ✓ | ✓ |
| 410 | darrin_pfeiffer country_of_citizenship | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 411 | srboljub_markušević occupation | association_football_mana | association_football_play | ✗ | ✓ |
| 412 | le_mans distributor | national_general_pictures | national_general_pictures | ✓ | ✓ |
| 413 | agrostis_trachychlaena taxon_rank | species | species | ✓ | ✓ |
| 414 | jay_sparrow instance_of | human | human | ✓ | ✓ |
| 415 | acrobatic_dog-fight instance_of | video_game | video_game | ✓ | ✓ |
| 416 | la_chair_de_l'orchidée composer | fiorenzo_carpi | fiorenzo_carpi | ✓ | ✓ |
| 417 | brian_heward occupation | association_football_play | association_football_play | ✓ | ✓ |
| 418 | richard_steinheimer instance_of | human | human | ✓ | ✓ |
| 419 | sakurabashi_station connecting_line | shizuoka–shimizu_line | shizuoka–shimizu_line | ✓ | ✓ |
| 420 | waru cast_member | atsuko_sakuraba | atsuko_sakuraba | ✓ | ✓ |
| 421 | viktor_savelyev award_received | hero_of_socialist_labour | state_prize_of_the_russia | ✗ | ✗ |
| 422 | edward_stanley,_2nd_baron_stanley_of_alderley given_nam | edward | edward | ✓ | ✓ |
| 423 | bell_street_bus_station country | australia | australia | ✓ | ✓ |
| 424 | georges_dufayel instance_of | human | human | ✓ | ✓ |
| 425 | kağan_timurcin_konuk occupation | association_football_play | association_football_play | ✓ | ✓ |
| 426 | dhimitër_pasko country_of_citizenship | albania | albania | ✓ | ✓ |
| 427 | andersonville located_in_time_zone | eastern_time_zone | utc−05:00 | ✗ | ✓ |
| 428 | oweekeno country | canada | canada | ✓ | ✓ |
| 429 | gavriel_zev_margolis place_of_death | new_york_city | new_york_city | ✓ | ✓ |
| 430 | ankfy1 chromosome | human_chromosome_17 | human_chromosome_17 | ✓ | ✓ |
| 431 | dr._wake's_patient original_language_of_film_or_tv_show | english | english | ✓ | ✓ |
| 432 | frank_henderson educated_at | university_of_idaho | university_of_idaho | ✓ | ✓ |
| 433 | uss_braziliera location_of_final_assembly | baltimore | baltimore | ✓ | ✓ |
| 434 | austin_reed instance_of | human | business | ✗ | ✓ |
| 435 | fran_brodić member_of_sports_team | croatia_national_under-18 | n.k._dinamo_zagreb | ✗ | ✗ |
| 436 | m45_motorway terminus_location | watford_gap | watford_gap | ✓ | ✓ |
| 437 | ramshir located_in_the_administrative_territorial_entit | central_district | central_district | ✓ | ✓ |
| 438 | échassières located_in_time_zone | utc+01:00 | utc+02:00 | ✗ | ✓ |
| 439 | yaroslav_deda member_of_sports_team | fc_volyn_lutsk | fc_volyn_lutsk | ✓ | ✓ |
| 440 | john_collier languages_spoken,_written_or_signed | english | english | ✓ | ✓ |
| 441 | fernando_de_moraes member_of_sports_team | australia_national_futsal | australia_national_futsal | ✓ | ✓ |
| 442 | trumaker_&_co. country | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 443 | bernard_malamud notable_work | the_magic_barrel | the_assistant | ✗ | ✗ |
| 444 | dunkirk,_nottingham country | united_kingdom | united_kingdom | ✓ | ✓ |
| 445 | all_hands_on_deck part_of | aquarius | aquarius | ✓ | ✓ |
| 446 | musō_soseki languages_spoken,_written_or_signed | japanese | japanese | ✓ | ✓ |
| 447 | return_of_the_living_dead_part_ii cast_member | james_karen | phil_bruns | ✗ | ✓ |
| 448 | seven_men_from_now genre | western_film | western_film | ✓ | ✓ |
| 449 | patrick_m'boma given_name | patrick | patrick | ✓ | ✓ |
| 450 | æneas_mackenzie instance_of | human | human | ✓ | ✓ |
| 451 | northern_dancer color | bay | bay | ✓ | ✓ |
| 452 | list_of_uk_r&b_singles_chart_number_ones_of_2016 instan | wikimedia_list_article | wikimedia_list_article | ✓ | ✓ |
| 453 | harry_potter_and_the_order_of_the_phoenix filming_locat | turkey | hertfordshire | ✗ | ✓ |
| 454 | ng_eng_hen instance_of | human | human | ✓ | ✓ |
| 455 | joaquín_argamasilla given_name | joaquín | joaquín | ✓ | ✓ |
| 456 | tim_castille member_of_sports_team | kansas_city_chiefs | arizona_cardinals | ✗ | ✓ |
| 457 | gabriela_silang country_of_citizenship | philippines | philippines | ✓ | ✓ |
| 458 | blake_berris place_of_birth | los_angeles | los_angeles | ✓ | ✓ |
| 459 | mike_sandbothe employer | berlin_university_of_the_ | berlin_university_of_the_ | ✓ | ✓ |
| 460 | lincoln_mks powered_by | petrol_engine | petrol_engine | ✓ | ✓ |
| 461 | tales_from_northumberland_with_robson_green country_of_ | united_kingdom | united_kingdom | ✓ | ✓ |
| 462 | 2015–16_isthmian_league sport | association_football | association_football | ✓ | ✓ |
| 463 | ramon_d'abadal_i_de_vinyals educated_at | university_of_barcelona | university_of_barcelona | ✓ | ✓ |
| 464 | corsair country_of_origin | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 465 | hybothecus_flohri instance_of | taxon | taxon | ✓ | ✓ |
| 466 | chilean_navy country | chile | chile | ✓ | ✓ |
| 467 | tridens instance_of | taxon | taxon | ✓ | ✓ |
| 468 | sahar_youssef participant_of | 1984_summer_olympics | 1984_summer_olympics | ✓ | ✓ |
| 469 | rhododendron_phaeochrysum parent_taxon | rhododendron | rhododendron | ✓ | ✓ |
| 470 | lesley_garrett voice_type | soprano | soprano | ✓ | ✓ |
| 471 | fort_franklin_battlespace_laboratory located_in_the_adm | massachusetts | massachusetts | ✓ | ✓ |
| 472 | rafael_barbosa_do_nascimento sport | association_football | association_football | ✓ | ✓ |
| 473 | nikola_aksentijević member_of_sports_team | vitesse | serbia_national_under-17_ | ✗ | ✓ |
| 474 | 2017_tirreno–adriatico participating_team | bahrain-merida_2017 | sky_2017 | ✗ | ✓ |
| 475 | ouray_mine instance_of | mine | mine | ✓ | ✓ |
| 476 | code_of_the_outlaw country_of_origin | united_states_of_america | united_states_of_america | ✓ | ✓ |
| 477 | x_factor_georgia original_network | rustavi_2 | rustavi_2 | ✓ | ✓ |
| 478 | those_who_were_hung_hang_here followed_by | modern_currencies | (none) | ✗ | ✗ |
| 479 | anyamaru_tantei_kiruminzuu genre | shōjo | shōjo | ✓ | ✓ |
| 480 | bouchaib_el_moubarki member_of_sports_team | al_ahli_sc | al_ahli_sc | ✓ | ✓ |
| 481 | frits_zernike place_of_death | amersfoort | amersfoort | ✓ | ✓ |
| 482 | ashraf_choudhary place_of_birth | sialkot | sialkot | ✓ | ✓ |
| 483 | david_grant sport | association_football | association_football | ✓ | ✓ |
| 484 | the_good_night cast_member | penélope_cruz | martin_freeman | ✗ | ✗ |
| 485 | 1947_tour_de_france,_stage_1_to_stage_11 country | france | france | ✓ | ✓ |
| 486 | henry_stafford,_2nd_duke_of_buckingham child | elizabeth_stafford,_count | elizabeth_stafford,_count | ✓ | ✓ |
| 487 | 2005–06_ligue_magnus_season country | france | france | ✓ | ✓ |
| 488 | province_of_messina contains_administrative_territorial | reitano | montagnareale | ✗ | ✗ |
| 489 | evan_taylor member_of_sports_team | harbour_view_f.c. | vancouver_whitecaps_fc_re | ✗ | ✓ |
| 490 | christina_hengster languages_spoken,_written_or_signed | german | german | ✓ | ✓ |
| 491 | malegoude shares_border_with | seignalens | sainte-foi | ✗ | ✓ |
| 492 | magna_carta contributor(s)_to_the_creative_work_or_subj | caroline_lucas | kenneth_clarke | ✗ | ✗ |
| 493 | wilshire located_in_the_administrative_territorial_enti | california | california | ✓ | ✓ |
| 494 | nemanja_miletić member_of_sports_team | fk_sloga_kraljevo | fk_radnički_stobex | ✗ | ✗ |
| 495 | mainframe_sort_merge instance_of | software | software | ✓ | ✓ |
| 496 | harald_feller instance_of | human | human | ✓ | ✓ |
| 497 | steve_mcmanaman sport | association_football | association_football | ✓ | ✓ |
| 498 | max_speter given_name | max | max | ✓ | ✓ |
| 499 | gertrude_abercrombie employer | works_progress_administra | works_progress_administra | ✓ | ✓ |
| 500 | sriranjani occupation | actor | actor | ✓ | ✓ |

---

## Mode 2 — Chain-of-Thought (500)

| # | Query | Gold | Direct Hit@5 | CoT Hit@5 | Recovered | Hop 2 Via |
|---|-------|------|-------------|-----------|-----------|-----------|
| 1 | edward_c._campbell occupation | judge | ✓ | ✓ |  |  |
| 2 | y_felinheli instance_of | community | ✓ | ✓ |  |  |
| 3 | isher_judge_ahluwalia educated_at | massachusetts_institute_o | ✓ | ✓ |  |  |
| 4 | foxa1 instance_of | gene | ✓ | ✓ |  |  |
| 5 | ardentes shares_border_with | le_poinçonnet | ✓ | ✓ |  |  |
| 6 | tristin_mays instance_of | human | ✓ | ✓ |  |  |
| 7 | héctor_jiménez occupation | film_producer | ✓ | ✓ |  |  |
| 8 | otonica country | slovenia | ✓ | ✓ |  |  |
| 9 | popeye genre | action_game | ✓ | ✓ |  |  |
| 10 | gray_marine_motor_company headquarters_location | detroit | ✓ | ✓ |  |  |
| 11 | shan_vincent_de_paul instance_of | human | ✓ | ✓ |  |  |
| 12 | the_big_town instance_of | short_film | ✓ | ✓ |  |  |
| 13 | 1944_cleveland_rams_season sport | american_football | ✓ | ✓ |  |  |
| 14 | falborek located_in_time_zone | utc+01:00 | ✓ | ✓ |  |  |
| 15 | ernest_champion member_of_sports_team | charlton_athletic_f.c. | ✓ | ✓ |  |  |
| 16 | edward_boustead place_of_birth | yorkshire | ✓ | ✓ |  |  |
| 17 | m38_wolfhound instance_of | armored_car | ✓ | ✓ |  |  |
| 18 | krang present_in_work | teenage_mutant_ninja_turt | ✓ | ✓ |  |  |
| 19 | blind_man's_bluff instance_of | film | ✓ | ✓ |  |  |
| 20 | ciini instance_of | taxon | ✓ | ✓ |  |  |
| 21 | shameless country_of_origin | germany | ✓ | ✓ |  |  |
| 22 | bazar_house_in_miłosław located_in_the_administrat | miłosław | ✓ | ✓ |  |  |
| 23 | bill_bailey given_name | bill | ✓ | ✓ |  |  |
| 24 | helene_weber country_of_citizenship | germany | ✓ | ✓ |  |  |
| 25 | franz_von_seitz given_name | franz | ✓ | ✓ |  |  |
| 26 | hugh_hefner:_playboy,_activist_and_rebel cast_memb | jenny_mccarthy | ✓ | ✓ |  |  |
| 27 | george_anderson place_of_death | canada | ✓ | ✓ |  |  |
| 28 | laynce_nix handedness | left-handedness | ✓ | ✓ |  |  |
| 29 | piano instance_of | play | ✓ | ✓ |  |  |
| 30 | roman_bagration country_of_citizenship | georgia | ✓ | ✓ |  |  |
| 31 | united_nations_security_council_resolution_551 ins | united_nations_security_c | ✓ | ✓ |  |  |
| 32 | gustav_flatow place_of_death | theresienstadt_concentrat | ✓ | ✓ |  |  |
| 33 | ron_white occupation | songwriter | ✓ | ✓ |  |  |
| 34 | karin_kschwendt country_of_citizenship | austria | ✓ | ✓ |  |  |
| 35 | urubamba_mountain_range country | peru | ✓ | ✓ |  |  |
| 36 | written_language opposite_of | spoken_language | ✓ | ✓ |  |  |
| 37 | stefanowo,_masovian_voivodeship located_in_time_zo | utc+02:00 | ✓ | ✓ |  |  |
| 38 | choreutis_achyrodes taxon_rank | species | ✓ | ✓ |  |  |
| 39 | sigeberht instance_of | human | ✓ | ✓ |  |  |
| 40 | francesco_bracciolini occupation | writer | ✓ | ✓ |  |  |
| 41 | shine,_shine,_my_star genre | grotto-esque | ✓ | ✓ |  |  |
| 42 | premam composer | gopi_sundar | ✓ | ✓ |  |  |
| 43 | honghuli_station instance_of | metro_station | ✓ | ✓ |  |  |
| 44 | porrera shares_border_with | poboleda | ✗ | ✓ | ✓ SAVED | cornudella_de_montsant |
| 45 | george_r._johnson instance_of | human | ✓ | ✓ |  |  |
| 46 | ludmilla_of_bohemia spouse | louis_i | ✓ | ✓ |  |  |
| 47 | canty_bay instance_of | hamlet | ✓ | ✓ |  |  |
| 48 | halston cause_of_death | cancer | ✓ | ✓ |  |  |
| 49 | hans_wilhelm_frei award_received | john_simon_guggenheim_mem | ✓ | ✓ |  |  |
| 50 | the_little_thief director | claude_miller | ✓ | ✓ |  |  |
| 51 | mydas_luteipennis parent_taxon | mydas | ✓ | ✓ |  |  |
| 52 | tere_glassie instance_of | human | ✓ | ✓ |  |  |
| 53 | jordi_puigneró_i_ferrer instance_of | human | ✓ | ✓ |  |  |
| 54 | pedro_colón member_of_political_party | democratic_party | ✓ | ✓ |  |  |
| 55 | schnals located_in_time_zone | utc+01:00 | ✓ | ✓ |  |  |
| 56 | human_resources_university instance_of | university | ✓ | ✓ |  |  |
| 57 | general_post_office located_in_the_administrative_ | queensland | ✓ | ✓ |  |  |
| 58 | euphemia_of_rügen instance_of | human | ✓ | ✓ |  |  |
| 59 | antikensammlung_berlin instance_of | art_collection | ✓ | ✓ |  |  |
| 60 | château_de_cléron located_in_the_administrative_te | cléron | ✓ | ✓ |  |  |
| 61 | rescue_nunatak instance_of | mountain | ✓ | ✓ |  |  |
| 62 | vukašin_jovanović member_of_sports_team | serbia_national_under-19_ | ✓ | ✓ |  |  |
| 63 | my_losing_season publisher | nan_a._talese | ✓ | ✓ |  |  |
| 64 | australian_derby country | australia | ✓ | ✓ |  |  |
| 65 | helmut_kremers member_of_sports_team | germany_national_football | ✓ | ✓ |  |  |
| 66 | alyaksandr_alhavik member_of_sports_team | fc_khimik_svetlogorsk | ✓ | ✓ |  |  |
| 67 | gornje_gare located_in_time_zone | utc+01:00 | ✓ | ✓ |  |  |
| 68 | canton_of_jarnages contains_administrative_territo | saint-silvain-sous-toulx | ✗ | ✓ | ✓ SAVED | parsac |
| 69 | 1983_virginia_slims_of_washington_–_singles winner | martina_navratilova | ✓ | ✓ |  |  |
| 70 | ross_bentley country_of_citizenship | united_states_of_america | ✓ | ✓ |  |  |
| 71 | neuroscientist field_of_this_occupation | neuroscience | ✓ | ✓ |  |  |
| 72 | sucha_struga located_in_time_zone | utc+01:00 | ✓ | ✓ |  |  |
| 73 | beauty_and_the_beast significant_event | première | ✓ | ✓ |  |  |
| 74 | wilkins_highway country | australia | ✓ | ✓ |  |  |
| 75 | girl_in_the_cadillac cast_member | william_shockley | ✗ | ✓ | ✓ SAVED | erika_eleniak |
| 76 | jeziorki,_świecie_county located_in_the_administra | gmina_lniano | ✓ | ✓ |  |  |
| 77 | kaitō_royale country_of_origin | japan | ✓ | ✓ |  |  |
| 78 | fayette_high_school located_in_the_administrative_ | ohio | ✓ | ✓ |  |  |
| 79 | brice_dja_djédjé member_of_sports_team | olympique_de_marseille | ✓ | ✓ |  |  |
| 80 | dhunni instance_of | union_council_of_pakistan | ✓ | ✓ |  |  |
| 81 | 1991_asian_women's_handball_championship instance_ | asian_women's_handball_ch | ✓ | ✓ |  |  |
| 82 | the_lost_take record_label | anticon. | ✓ | ✓ |  |  |
| 83 | curtner country | united_states_of_america | ✓ | ✓ |  |  |
| 84 | chemical_heart part_of | new_detention | ✓ | ✓ |  |  |
| 85 | dermacentor_circumguttatus taxon_rank | species | ✓ | ✓ |  |  |
| 86 | daniel_avery place_of_birth | groton | ✓ | ✓ |  |  |
| 87 | mansfield located_in_the_administrative_territoria | desoto_parish | ✗ | ✗ |  |  |
| 88 | clinton_solomon instance_of | human | ✓ | ✓ |  |  |
| 89 | the_evolution_of_gospel performer | sounds_of_blackness | ✓ | ✓ |  |  |
| 90 | joel_feeney place_of_birth | oakville | ✓ | ✓ |  |  |
| 91 | shareef_adnan member_of_sports_team | shabab_al-ordon_club | ✓ | ✓ |  |  |
| 92 | shadiwal_hydropower_plant instance_of | hydroelectric_power_stati | ✓ | ✓ |  |  |
| 93 | national_cycle_route_75 instance_of | long-distance_cycling_rou | ✓ | ✓ |  |  |
| 94 | det_gælder_os_alle genre | drama_film | ✓ | ✓ |  |  |
| 95 | upplanda located_in_time_zone | utc+02:00 | ✓ | ✓ |  |  |
| 96 | south_pasadena_unified_school_district located_in_ | california | ✓ | ✓ |  |  |
| 97 | karl_brunner given_name | karl | ✓ | ✓ |  |  |
| 98 | rehoboth_ratepayers'_association headquarters_loca | rehoboth | ✓ | ✓ |  |  |
| 99 | 2012_thai_division_1_league sports_season_of_leagu | thai_division_1_league | ✓ | ✓ |  |  |
| 100 | georges_semichon given_name | george | ✓ | ✓ |  |  |
| 101 | baphia_puguensis iucn_conservation_status | endangered_species | ✓ | ✓ |  |  |
| 102 | al_son_de_la_marimba cast_member | sara_garcía | ✓ | ✓ |  |  |
| 103 | cary_brothers country_of_citizenship | united_states_of_america | ✓ | ✓ |  |  |
| 104 | thomas_fitzgibbon_moore instance_of | human | ✓ | ✓ |  |  |
| 105 | anthony_cooke given_name | anthony | ✓ | ✓ |  |  |
| 106 | richard_williams educated_at | mississippi_state_univers | ✓ | ✓ |  |  |
| 107 | simone_le_bargy occupation | actor | ✓ | ✓ |  |  |
| 108 | avengers:_infinity_war cast_member | paul_bettany | ✗ | ✓ | ✓ SAVED | scarlett_johansson |
| 109 | antipas_of_pergamum country_of_citizenship | ancient_rome | ✓ | ✓ |  |  |
| 110 | between_friends cast_member | lou_tellegen | ✓ | ✓ |  |  |
| 111 | the_age_of_adaline cast_member | harrison_ford | ✗ | ✓ | ✓ SAVED | blake_lively |
| 112 | list_of_first_ladies_of_cameroon is_a_list_of | person | ✓ | ✓ |  |  |
| 113 | auzeville-tolosane shares_border_with | pechbusque | ✓ | ✓ |  |  |
| 114 | eudonia_australialis parent_taxon | eudonia | ✓ | ✓ |  |  |
| 115 | cass_building architect | smithgroup | ✓ | ✓ |  |  |
| 116 | jan_kmenta employer | university_of_michigan | ✓ | ✓ |  |  |
| 117 | paul_freeman educated_at | eastman_school_of_music | ✓ | ✓ |  |  |
| 118 | karin_söder instance_of | human | ✓ | ✓ |  |  |
| 119 | the_mice cast_member | henry_silva | ✓ | ✓ |  |  |
| 120 | tomás_herrera_martínez participant_of | 1972_summer_olympics | ✓ | ✓ |  |  |
| 121 | james_pritchard instance_of | human | ✓ | ✓ |  |  |
| 122 | 1280_in_poetry facet_of | poetry | ✓ | ✓ |  |  |
| 123 | somatina_accraria instance_of | taxon | ✓ | ✓ |  |  |
| 124 | paul_massey instance_of | human | ✓ | ✓ |  |  |
| 125 | pyrausta_sanguinalis taxon_rank | species | ✓ | ✓ |  |  |
| 126 | snuggle_truck game_mode | single-player_video_game | ✓ | ✓ |  |  |
| 127 | frederick_fitzclarence given_name | frederick | ✓ | ✓ |  |  |
| 128 | michael_cartellone instrument | drum_kit | ✓ | ✓ |  |  |
| 129 | niphoparmena_latifrons parent_taxon | niphoparmena | ✓ | ✓ |  |  |
| 130 | cité_du_niger country | mali | ✓ | ✓ |  |  |
| 131 | tsarevich_dmitry_alexeyevich_of_russia sibling | sophia_alekseyevna_of_rus | ✗ | ✓ | ✓ SAVED | tsarevna_natalya_alexeevn |
| 132 | dancing_in_water cast_member | petar_banićević | ✗ | ✗ |  |  |
| 133 | echunga country | australia | ✓ | ✓ |  |  |
| 134 | nesoptilotis instance_of | taxon | ✓ | ✓ |  |  |
| 135 | maximilian,_crown_prince_of_saxony sibling | princess_maria_amalia_of_ | ✓ | ✓ |  |  |
| 136 | 2013_tatarstan_open_–_doubles sport | tennis | ✓ | ✓ |  |  |
| 137 | the_day_of_the_owl language_of_work_or_name | italian | ✓ | ✓ |  |  |
| 138 | catch_me_if_you_can instance_of | album | ✗ | ✗ |  |  |
| 139 | oleszki located_in_the_administrative_territorial_ | gmina_busko-zdrój | ✓ | ✓ |  |  |
| 140 | johann_christian_von_stramberg occupation | historian | ✓ | ✓ |  |  |
| 141 | denis_kapochkin member_of_sports_team | fc_nara-shbfr_naro-fomins | ✓ | ✓ |  |  |
| 142 | brad_isbister instance_of | human | ✓ | ✓ |  |  |
| 143 | phaethontidae parent_taxon | phaethontiformes | ✓ | ✓ |  |  |
| 144 | the_house_of_the_seven_gables production_designer | jack_otterson | ✓ | ✓ |  |  |
| 145 | dean_of_ferns instance_of | wikimedia_list_article | ✓ | ✓ |  |  |
| 146 | propilidium_pertenue taxon_rank | species | ✓ | ✓ |  |  |
| 147 | br.1050_alizé armament | depth_charge | ✓ | ✓ |  |  |
| 148 | olbrachcice,_masovian_voivodeship located_in_time_ | utc+02:00 | ✓ | ✓ |  |  |
| 149 | gega_diasamidze occupation | association_football_play | ✓ | ✓ |  |  |
| 150 | patinoire_de_malley owned_by | prilly | ✓ | ✓ |  |  |
| 151 | aleksey_petrovich_yermolov conflict | napoleonic_wars | ✓ | ✓ |  |  |
| 152 | i_hate_you_now... genre | pop_music | ✓ | ✓ |  |  |
| 153 | nanda_devi_national_park heritage_designation | unesco_world_heritage_sit | ✓ | ✓ |  |  |
| 154 | buldhana_vidhan_sabha_constituency country | india | ✓ | ✓ |  |  |
| 155 | camden_airstrip instance_of | airport | ✓ | ✓ |  |  |
| 156 | university_of_california,_irvine has_part | school_of_education | ✗ | ✗ |  |  |
| 157 | mühlanger country | germany | ✓ | ✓ |  |  |
| 158 | ștefan_cel_mare located_in_the_administrative_terr | neamț_county | ✓ | ✓ |  |  |
| 159 | michael_f._guyer instance_of | human | ✓ | ✓ |  |  |
| 160 | volume_1:_65's.late.nite.double-a-side.college.cut | album | ✓ | ✓ |  |  |
| 161 | far_cry producer | nick_raskulinecz | ✓ | ✓ |  |  |
| 162 | pilocrocis_cuprescens parent_taxon | pilocrocis | ✓ | ✓ |  |  |
| 163 | hughie_dow member_of_sports_team | sunderland_a.f.c. | ✓ | ✓ |  |  |
| 164 | adalbert_iii_of_saxony sibling | margaret_of_saxony,_duche | ✓ | ✓ |  |  |
| 165 | george_herbert,_8th_earl_of_carnarvon educated_at | eton_college | ✓ | ✓ |  |  |
| 166 | benjamin_heywood languages_spoken,_written_or_sign | english | ✓ | ✓ |  |  |
| 167 | tashkent_mechanical_plant instance_of | business | ✓ | ✓ |  |  |
| 168 | jealous record_label | parlophone | ✓ | ✓ |  |  |
| 169 | valentin_bădoi position_played_on_team | midfielder | ✓ | ✓ |  |  |
| 170 | bright_lights:_starring_carrie_fisher_and_debbie_r | debbie_reynolds | ✓ | ✓ |  |  |
| 171 | ace_of_aces producer | horst_wendlandt | ✓ | ✓ |  |  |
| 172 | gennaro_fragiello member_of_sports_team | a.c._carpenedolo | ✗ | ✓ | ✓ SAVED | bologna_f.c._1909 |
| 173 | tiago_jonas place_of_birth | porto | ✓ | ✓ |  |  |
| 174 | le_lyrial instance_of | cruise_ship | ✓ | ✓ |  |  |
| 175 | knut_johannesen country_of_citizenship | norway | ✓ | ✓ |  |  |
| 176 | marco_airosa member_of_sports_team | angola_national_football_ | ✗ | ✓ | ✓ SAVED | g.d.p._costa_de_caparica |
| 177 | james_vasquez instance_of | human | ✓ | ✓ |  |  |
| 178 | kaklamanis writing_system | greek_alphabet | ✓ | ✓ |  |  |
| 179 | harold_huntley_bassett occupation | military_officer | ✓ | ✓ |  |  |
| 180 | red_rock_bridge instance_of | bridge | ✓ | ✓ |  |  |
| 181 | sebastian_praus languages_spoken,_written_or_signe | german | ✓ | ✓ |  |  |
| 182 | franjo_džidić member_of_sports_team | nk_široki_brijeg | ✓ | ✓ |  |  |
| 183 | margherita_d'anjou librettist | felice_romani | ✓ | ✓ |  |  |
| 184 | villa_melnik_winery headquarters_location | harsovo,_blagoevgrad_prov | ✓ | ✓ |  |  |
| 185 | jamie_rauch place_of_birth | houston | ✓ | ✓ |  |  |
| 186 | pekka_sylvander participant_of | 1964_summer_olympics | ✓ | ✓ |  |  |
| 187 | female_agents cast_member | xavier_beauvois | ✓ | ✓ |  |  |
| 188 | yvelines contains_administrative_territorial_entit | le_mesnil-le-roi | ✗ | ✗ |  |  |
| 189 | vince_clarke bowling_style | leg_break | ✓ | ✓ |  |  |
| 190 | ashley_graham country_of_citizenship | australia | ✓ | ✓ |  |  |
| 191 | dreams_awake country_of_origin | united_states_of_america | ✓ | ✓ |  |  |
| 192 | sharove country | albania | ✓ | ✓ |  |  |
| 193 | men_without_a_fatherland cast_member | willi_schaeffers | ✗ | ✗ |  |  |
| 194 | israel_national_basketball_team instance_of | national_sports_team | ✓ | ✓ |  |  |
| 195 | françois-louis_français described_by_source | brockhaus_and_efron_encyc | ✓ | ✓ |  |  |
| 196 | kabile_island instance_of | island | ✓ | ✓ |  |  |
| 197 | conceptual_party_unity political_ideology | stalinism | ✓ | ✓ |  |  |
| 198 | davy_schollen member_of_sports_team | k.r.c._genk | ✓ | ✓ |  |  |
| 199 | robot_entertainment country | united_states_of_america | ✓ | ✓ |  |  |
| 200 | armands_zeiberliņš member_of_sports_team | ope_if | ✗ | ✓ | ✓ SAVED | latvia_national_football_ |
| 201 | carl_jung significant_person | sigmund_freud | ✓ | ✓ |  |  |
| 202 | red-shouldered_vanga parent_taxon | calicalicus | ✓ | ✓ |  |  |
| 203 | the_secret_war country_of_origin | united_kingdom | ✓ | ✓ |  |  |
| 204 | liebfrauen,_frankfurt located_in_the_administrativ | frankfurt | ✓ | ✓ |  |  |
| 205 | choi_min-ho given_name | min-ho | ✓ | ✓ |  |  |
| 206 | 1999_segunda_división_peruana instance_of | sports_season | ✓ | ✓ |  |  |
| 207 | extra_space_storage headquarters_location | cottonwood_heights | ✓ | ✓ |  |  |
| 208 | noel_hunt position_played_on_team | forward | ✓ | ✓ |  |  |
| 209 | kalmakanda_upazila country | bangladesh | ✓ | ✓ |  |  |
| 210 | baillif shares_border_with | basse-terre | ✓ | ✓ |  |  |
| 211 | rayappanur country | india | ✓ | ✓ |  |  |
| 212 | haute-marne contains_administrative_territorial_en | vaudrémont | ✗ | ✗ |  |  |
| 213 | carlos_turrubiates position_played_on_team | defender | ✓ | ✓ |  |  |
| 214 | nevin_william_hayes instance_of | human | ✓ | ✓ |  |  |
| 215 | john_gillespie member_of_sports_team | scotland_national_rugby_u | ✓ | ✓ |  |  |
| 216 | john_george_walker place_of_birth | jefferson_city | ✓ | ✓ |  |  |
| 217 | maumee-class_oiler followed_by | usns_american_explorer | ✓ | ✓ |  |  |
| 218 | vullnet_basha member_of_sports_team | grasshopper_club_zürich | ✓ | ✓ |  |  |
| 219 | ray_ozzie educated_at | university_of_illinois_sy | ✓ | ✓ |  |  |
| 220 | katharine_ross spouse | sam_elliott | ✓ | ✓ |  |  |
| 221 | sringaram cast_member | aditi_rao_hydari | ✓ | ✓ |  |  |
| 222 | pacific_leaping_blenny parent_taxon | alticus | ✓ | ✓ |  |  |
| 223 | shake_your_rump followed_by | johnny_ryall | ✓ | ✓ |  |  |
| 224 | jenny_valentine educated_at | goldsmiths,_university_of | ✓ | ✓ |  |  |
| 225 | siddharth_gupta instance_of | human | ✓ | ✓ |  |  |
| 226 | 1990–91_leicester_city_f.c._season sport | association_football | ✓ | ✓ |  |  |
| 227 | sailors'_snug_harbor part_of | new_york_city_subway | ✓ | ✓ |  |  |
| 228 | the_foreman_of_the_jury cast_member | roscoe_arbuckle | ✓ | ✓ |  |  |
| 229 | anno_2205 instance_of | video_game | ✓ | ✓ |  |  |
| 230 | private_confessions cast_member | hans_alfredson | ✗ | ✓ | ✓ SAVED | kristina_adolphson |
| 231 | boy_trouble color | black-and-white | ✓ | ✓ |  |  |
| 232 | chester_ray_benjamin educated_at | university_of_iowa | ✓ | ✓ |  |  |
| 233 | creature instance_of | studio_album | ✗ | ✓ | ✓ SAVED | film |
| 234 | angus_maclaine instance_of | human | ✓ | ✓ |  |  |
| 235 | the_slammin'_salmon cast_member | cobie_smulders | ✗ | ✗ |  |  |
| 236 | i'm_going_home_to_dixie instance_of | song | ✓ | ✓ |  |  |
| 237 | archinform instance_of | encyclopedia | ✓ | ✓ |  |  |
| 238 | carry_on..._up_the_khyber country_of_origin | united_kingdom | ✓ | ✓ |  |  |
| 239 | king_abdullah_design_and_development_bureau headqu | amman | ✓ | ✓ |  |  |
| 240 | dorfstetten located_in_time_zone | utc+02:00 | ✓ | ✓ |  |  |
| 241 | universitas_psychologica publisher | pontifical_xavierian_univ | ✓ | ✓ |  |  |
| 242 | yevhen_drahunov place_of_birth | makiivka | ✓ | ✓ |  |  |
| 243 | julius_caesar award_received | golden_leopard | ✓ | ✓ |  |  |
| 244 | andrei_sidorenkov member_of_sports_team | viljandi_jk_tulevik | ✗ | ✗ |  |  |
| 245 | bob_perry member_of_sports_team | fall_river_marksmen | ✓ | ✓ |  |  |
| 246 | mitch_glazer spouse | kelly_lynch | ✓ | ✓ |  |  |
| 247 | amirabad,_faruj country | iran | ✓ | ✓ |  |  |
| 248 | são_mamede country | portugal | ✓ | ✓ |  |  |
| 249 | holley_central_school_district located_in_the_admi | new_york | ✓ | ✓ |  |  |
| 250 | es_migjorn_gran located_in_or_next_to_body_of_wate | mediterranean_sea | ✓ | ✓ |  |  |
| 251 | baby_blue_marine director | john_d._hancock | ✓ | ✓ |  |  |
| 252 | aeromonas_fluvialis parent_taxon | aeromonas | ✓ | ✓ |  |  |
| 253 | bhairava_dweepam country_of_origin | india | ✓ | ✓ |  |  |
| 254 | leon_mettam instance_of | human | ✓ | ✓ |  |  |
| 255 | dean_collis country_of_citizenship | australia | ✓ | ✓ |  |  |
| 256 | list_of_libraries_in_the_palestinian_territories s | list_of_libraries_by_coun | ✓ | ✓ |  |  |
| 257 | now_that's_what_i_call_music!_52 record_label | virgin_records | ✗ | ✗ |  |  |
| 258 | heine_meine country_of_citizenship | united_states_of_america | ✓ | ✓ |  |  |
| 259 | epacris_calvertiana taxon_rank | species | ✓ | ✓ |  |  |
| 260 | valea_neagră_river country | romania | ✓ | ✓ |  |  |
| 261 | kwns located_in_the_administrative_territorial_ent | texas | ✓ | ✓ |  |  |
| 262 | north_african_ostrich taxon_rank | subspecies | ✓ | ✓ |  |  |
| 263 | rex_hudson country_of_citizenship | united_states_of_america | ✓ | ✓ |  |  |
| 264 | świerzowa_polska located_in_time_zone | utc+01:00 | ✓ | ✓ |  |  |
| 265 | besalampy_airport instance_of | airport | ✓ | ✓ |  |  |
| 266 | flag_of_rwanda color | blue | ✓ | ✓ |  |  |
| 267 | mark_robinson place_of_birth | belfast | ✗ | ✓ | ✓ SAVED | kingston_upon_hull |
| 268 | james_gamble member_of_political_party | democratic_party | ✓ | ✓ |  |  |
| 269 | simone_assemani place_of_death | padua | ✓ | ✓ |  |  |
| 270 | tunde_ke_kabab country_of_origin | india | ✓ | ✓ |  |  |
| 271 | kunihiro_hasegawa given_name | kunihiro | ✓ | ✓ |  |  |
| 272 | st_nectan's_church,_hartland named_after | nectan_of_hartland | ✓ | ✓ |  |  |
| 273 | 2017_open_bnp_paribas_banque_de_bretagne_–_singles | tennis | ✓ | ✓ |  |  |
| 274 | bathytoma_murdochi instance_of | taxon | ✓ | ✓ |  |  |
| 275 | princess_lalla_meryem_of_morocco sibling | hasna_of_morocco | ✓ | ✓ |  |  |
| 276 | tyne_valley-linkletter located_in_the_administrati | prince_edward_island | ✓ | ✓ |  |  |
| 277 | aretas_akers-douglas,_2nd_viscount_chilston place_ | kent | ✓ | ✓ |  |  |
| 278 | agua_mala part_of | the_x-files,_season_6 | ✓ | ✓ |  |  |
| 279 | jean_thomas_guillaume_lorge place_of_death | chauconin-neufmontiers | ✓ | ✓ |  |  |
| 280 | irmgard_griss occupation | politician | ✓ | ✓ |  |  |
| 281 | guynesomia instance_of | taxon | ✓ | ✓ |  |  |
| 282 | sun_longjiang participant_of | 2010_winter_olympics | ✓ | ✓ |  |  |
| 283 | keena_turner country_of_citizenship | united_states_of_america | ✓ | ✓ |  |  |
| 284 | fiery-capped_manakin taxon_rank | species | ✓ | ✓ |  |  |
| 285 | hyatt_place_waikiki_beach country | united_states_of_america | ✓ | ✓ |  |  |
| 286 | johann_gotthard_von_müller instance_of | human | ✓ | ✓ |  |  |
| 287 | czechoslovakia head_of_state | václav_havel | ✓ | ✓ |  |  |
| 288 | heinrich_nickel country_of_citizenship | germany | ✓ | ✓ |  |  |
| 289 | beyond_the_law cast_member | charlie_sheen | ✓ | ✓ |  |  |
| 290 | placogobio parent_taxon | cyprinidae | ✓ | ✓ |  |  |
| 291 | somerville_college part_of | university_of_oxford | ✓ | ✓ |  |  |
| 292 | il_profeta cast_member | liana_orfei | ✓ | ✓ |  |  |
| 293 | jhouwa_guthi located_in_time_zone | utc+05:45 | ✓ | ✓ |  |  |
| 294 | death_in_five_boxes country_of_origin | united_kingdom | ✓ | ✓ |  |  |
| 295 | art_schwind place_of_death | sullivan | ✓ | ✓ |  |  |
| 296 | kurt_ploeger given_name | kurt | ✓ | ✓ |  |  |
| 297 | pleven_province contains_administrative_territoria | pleven_municipality | ✗ | ✓ | ✓ SAVED | knezha_municipality |
| 298 | paddy_mclaughlin member_of_sports_team | harrogate_town_a.f.c. | ✓ | ✓ |  |  |
| 299 | ché_ahn country_of_citizenship | united_states_of_america | ✓ | ✓ |  |  |
| 300 | wolfgang_wolf member_of_sports_team | stuttgarter_kickers | ✓ | ✓ |  |  |
| 301 | stand_tall cast_member | arnold_schwarzenegger | ✓ | ✓ |  |  |
| 302 | splendrillia_woodringi taxon_rank | species | ✓ | ✓ |  |  |
| 303 | sutton_hall architect | cass_gilbert | ✓ | ✓ |  |  |
| 304 | control cast_member | michelle_rodriguez | ✗ | ✗ |  |  |
| 305 | danièle_sallenave occupation | journalist | ✓ | ✓ |  |  |
| 306 | kieron_barry instance_of | human | ✓ | ✓ |  |  |
| 307 | paulo_césar_arruda_parente member_of_sports_team | fluminense_f.c. | ✓ | ✓ |  |  |
| 308 | lucas_thwala member_of_sports_team | supersport_united_f.c. | ✓ | ✓ |  |  |
| 309 | frank_killam instance_of | human | ✓ | ✓ |  |  |
| 310 | encore..._for_future_generations language_of_work_ | english | ✓ | ✓ |  |  |
| 311 | luke_sikma country_of_citizenship | united_states_of_america | ✓ | ✓ |  |  |
| 312 | joel_carroll participant_of | 2012_summer_olympics | ✓ | ✓ |  |  |
| 313 | ottmar_edenhofer occupation | economist | ✓ | ✓ |  |  |
| 314 | new_riegel_high_school instance_of | state_school | ✓ | ✓ |  |  |
| 315 | david_sánchez_parrilla place_of_birth | tarragona | ✓ | ✓ |  |  |
| 316 | patrick_zelbel country_of_citizenship | germany | ✓ | ✓ |  |  |
| 317 | andrés_roa instance_of | human | ✓ | ✓ |  |  |
| 318 | insurial instance_of | business | ✓ | ✓ |  |  |
| 319 | john_holmstrom occupation | cartoonist | ✓ | ✓ |  |  |
| 320 | neola_semiaurata taxon_rank | species | ✓ | ✓ |  |  |
| 321 | kufra instance_of | oasis | ✓ | ✓ |  |  |
| 322 | cecily_mary_wise_pickerill occupation | surgeon | ✓ | ✓ |  |  |
| 323 | john_treacher instance_of | human | ✓ | ✓ |  |  |
| 324 | thomas_a._swayze,_jr. place_of_birth | tacoma | ✓ | ✓ |  |  |
| 325 | nuclear_weapons_convention instance_of | treaty | ✓ | ✓ |  |  |
| 326 | jamil_azzaoui given_name | jamil | ✓ | ✓ |  |  |
| 327 | rgs11 chromosome | human_chromosome_16 | ✓ | ✓ |  |  |
| 328 | seo_district instance_of | district_of_south_korea | ✓ | ✓ |  |  |
| 329 | belarus–russia_border country | belarus | ✓ | ✓ |  |  |
| 330 | les_carter instance_of | human | ✓ | ✓ |  |  |
| 331 | time shares_border_with | hå | ✓ | ✓ |  |  |
| 332 | priseltsi,_varna_province located_in_time_zone | utc+02:00 | ✓ | ✓ |  |  |
| 333 | confessions_of_an_english_opium-eater language_of_ | english | ✓ | ✓ |  |  |
| 334 | claude_delay given_name | claude | ✓ | ✓ |  |  |
| 335 | fis_ski-flying_world_championships_1977 sport | ski_jumping | ✓ | ✓ |  |  |
| 336 | trudy_silver instance_of | human | ✓ | ✓ |  |  |
| 337 | victor_lustig instance_of | human | ✓ | ✓ |  |  |
| 338 | oscar_fernández participant_of | 1996_summer_olympics | ✓ | ✓ |  |  |
| 339 | george_p._fletcher country_of_citizenship | united_states_of_america | ✓ | ✓ |  |  |
| 340 | william_howard_taft employer | yale_law_school | ✓ | ✓ |  |  |
| 341 | william_cullen,_baron_cullen_of_whitekirk educated | university_of_edinburgh | ✓ | ✓ |  |  |
| 342 | kenni_fisilau member_of_sports_team | plymouth_albion_r.f.c. | ✓ | ✓ |  |  |
| 343 | yasmine_pahlavi country_of_citizenship | iran | ✓ | ✓ |  |  |
| 344 | rodnay_zaks field_of_work | computer_science | ✓ | ✓ |  |  |
| 345 | ben_cauchi occupation | photographer | ✓ | ✓ |  |  |
| 346 | 2015_afghan_premier_league instance_of | sports_season | ✓ | ✓ |  |  |
| 347 | monark_starstalker from_fictional_universe | marvel_universe | ✓ | ✓ |  |  |
| 348 | bernhard_von_langenbeck given_name | bernhard | ✓ | ✓ |  |  |
| 349 | tony_denman instance_of | human | ✓ | ✓ |  |  |
| 350 | niels_helveg_petersen position_held | minister_of_economic_and_ | ✓ | ✓ |  |  |
| 351 | petite_formation instance_of | formation | ✓ | ✓ |  |  |
| 352 | la_odalisca_no._13 country_of_origin | mexico | ✓ | ✓ |  |  |
| 353 | who's_harry_crumb? genre | comedy_film | ✓ | ✓ |  |  |
| 354 | olympiakos_nicosia_fc participant_of | 1951–52_cypriot_first_div | ✗ | ✗ |  |  |
| 355 | deep_thought sport | chess | ✓ | ✓ |  |  |
| 356 | reginald_wynn_owen instance_of | human | ✓ | ✓ |  |  |
| 357 | bill_white member_of_sports_team | newport_county_a.f.c. | ✗ | ✓ | ✓ SAVED | philadelphia_phillies |
| 358 | burmese_american instance_of | ethnic_group | ✓ | ✓ |  |  |
| 359 | university_of_calgary_faculty_of_arts located_in_t | calgary | ✓ | ✓ |  |  |
| 360 | smarcc1 found_in_taxon | homo_sapiens | ✓ | ✓ |  |  |
| 361 | dermival_almeida_lima member_of_sports_team | brasiliense_futebol_clube | ✗ | ✗ |  |  |
| 362 | megachile_digna instance_of | taxon | ✓ | ✓ |  |  |
| 363 | grzegorz_tkaczyk member_of_sports_team | pge_vive_kielce | ✓ | ✓ |  |  |
| 364 | a-1_pictures instance_of | animation_studio | ✓ | ✓ |  |  |
| 365 | ipoh country | malaysia | ✓ | ✓ |  |  |
| 366 | kees_van_ierssel instance_of | human | ✓ | ✓ |  |  |
| 367 | il_gatto cast_member | mariangela_melato | ✗ | ✓ | ✓ SAVED | dalila_di_lazzaro |
| 368 | tentax_bruneii taxon_rank | species | ✓ | ✓ |  |  |
| 369 | poison_ivy country_of_origin | united_states_of_america | ✓ | ✓ |  |  |
| 370 | oktyabr' country | kyrgyzstan | ✓ | ✓ |  |  |
| 371 | uss_darke country | united_states_of_america | ✓ | ✓ |  |  |
| 372 | vincent_moscaritolo occupation | engineer | ✓ | ✓ |  |  |
| 373 | 20_dakika original_language_of_film_or_tv_show | turkish | ✓ | ✓ |  |  |
| 374 | city_of_tiny_lights distributor | icon_productions | ✓ | ✓ |  |  |
| 375 | elkin_blanco occupation | association_football_play | ✓ | ✓ |  |  |
| 376 | steve_adams member_of_sports_team | swindon_town_f.c. | ✗ | ✗ |  |  |
| 377 | billy_bibby_&_the_wry_smiles genre | rock_music | ✓ | ✓ |  |  |
| 378 | the_famous_jett_jackson cast_member | ryan_sommers_baum | ✓ | ✓ |  |  |
| 379 | hans_rudi_erdt instance_of | human | ✓ | ✓ |  |  |
| 380 | küttigen country | switzerland | ✓ | ✓ |  |  |
| 381 | mindanao_miniature_babbler iucn_conservation_statu | data_deficient | ✓ | ✓ |  |  |
| 382 | disappear producer | howard_benson | ✓ | ✓ |  |  |
| 383 | the_winding_stair cast_member | alma_rubens | ✓ | ✓ |  |  |
| 384 | john_boorman instance_of | human | ✓ | ✓ |  |  |
| 385 | yankee_in_oz follows | merry_go_round_in_oz | ✓ | ✓ |  |  |
| 386 | 1830_united_kingdom_general_election follows | 1826_united_kingdom_gener | ✓ | ✓ |  |  |
| 387 | makita_ka_lang_muli original_language_of_film_or_t | filipino | ✓ | ✓ |  |  |
| 388 | burton_latimer twinned_administrative_body | castelnuovo_magra | ✓ | ✓ |  |  |
| 389 | matt_darey record_label | armada_music | ✓ | ✓ |  |  |
| 390 | jamy,_lublin_voivodeship located_in_time_zone | utc+01:00 | ✓ | ✓ |  |  |
| 391 | sir_robert_ferguson,_2nd_baronet languages_spoken, | english | ✓ | ✓ |  |  |
| 392 | eynhallow located_in_or_next_to_body_of_water | atlantic_ocean | ✓ | ✓ |  |  |
| 393 | powersite country | united_states_of_america | ✓ | ✓ |  |  |
| 394 | side_arms_hyper_dyne genre | shoot_'em_up | ✓ | ✓ |  |  |
| 395 | radu_i_of_wallachia spouse | kalinikia | ✓ | ✓ |  |  |
| 396 | mundi country | india | ✓ | ✓ |  |  |
| 397 | bccip chromosome | human_chromosome_10 | ✓ | ✓ |  |  |
| 398 | namibia:_the_struggle_for_liberation genre | war_film | ✓ | ✓ |  |  |
| 399 | the_narrow_road_to_the_deep_north author | richard_flanagan | ✓ | ✓ |  |  |
| 400 | pittosporum_dasycaulon taxon_rank | species | ✓ | ✓ |  |  |
| 401 | dean_stokes member_of_sports_team | armitage_90_f.c. | ✓ | ✓ |  |  |
| 402 | odawara located_in_time_zone | utc+09:00 | ✓ | ✓ |  |  |
| 403 | movement_of_the_national_left instance_of | political_party | ✓ | ✓ |  |  |
| 404 | zen_in_the_united_states subclass_of | buddhism_in_the_united_st | ✓ | ✓ |  |  |
| 405 | alex_whittle member_of_sports_team | liverpool_f.c. | ✓ | ✓ |  |  |
| 406 | crossings follows | little_things | ✓ | ✓ |  |  |
| 407 | kimberly_buys place_of_birth | sint-niklaas | ✓ | ✓ |  |  |
| 408 | emoción,_canto_y_guitarra performer | jorge_cafrune | ✓ | ✓ |  |  |
| 409 | william_t._martin allegiance | confederate_states_of_ame | ✓ | ✓ |  |  |
| 410 | darrin_pfeiffer country_of_citizenship | united_states_of_america | ✓ | ✓ |  |  |
| 411 | srboljub_markušević occupation | association_football_mana | ✓ | ✓ |  |  |
| 412 | le_mans distributor | national_general_pictures | ✓ | ✓ |  |  |
| 413 | agrostis_trachychlaena taxon_rank | species | ✓ | ✓ |  |  |
| 414 | jay_sparrow instance_of | human | ✓ | ✓ |  |  |
| 415 | acrobatic_dog-fight instance_of | video_game | ✓ | ✓ |  |  |
| 416 | la_chair_de_l'orchidée composer | fiorenzo_carpi | ✓ | ✓ |  |  |
| 417 | brian_heward occupation | association_football_play | ✓ | ✓ |  |  |
| 418 | richard_steinheimer instance_of | human | ✓ | ✓ |  |  |
| 419 | sakurabashi_station connecting_line | shizuoka–shimizu_line | ✓ | ✓ |  |  |
| 420 | waru cast_member | atsuko_sakuraba | ✓ | ✓ |  |  |
| 421 | viktor_savelyev award_received | hero_of_socialist_labour | ✗ | ✓ | ✓ SAVED | state_prize_of_the_russia |
| 422 | edward_stanley,_2nd_baron_stanley_of_alderley give | edward | ✓ | ✓ |  |  |
| 423 | bell_street_bus_station country | australia | ✓ | ✓ |  |  |
| 424 | georges_dufayel instance_of | human | ✓ | ✓ |  |  |
| 425 | kağan_timurcin_konuk occupation | association_football_play | ✓ | ✓ |  |  |
| 426 | dhimitër_pasko country_of_citizenship | albania | ✓ | ✓ |  |  |
| 427 | andersonville located_in_time_zone | eastern_time_zone | ✓ | ✓ |  |  |
| 428 | oweekeno country | canada | ✓ | ✓ |  |  |
| 429 | gavriel_zev_margolis place_of_death | new_york_city | ✓ | ✓ |  |  |
| 430 | ankfy1 chromosome | human_chromosome_17 | ✓ | ✓ |  |  |
| 431 | dr._wake's_patient original_language_of_film_or_tv | english | ✓ | ✓ |  |  |
| 432 | frank_henderson educated_at | university_of_idaho | ✓ | ✓ |  |  |
| 433 | uss_braziliera location_of_final_assembly | baltimore | ✓ | ✓ |  |  |
| 434 | austin_reed instance_of | human | ✓ | ✓ |  |  |
| 435 | fran_brodić member_of_sports_team | croatia_national_under-18 | ✗ | ✓ | ✓ SAVED | n.k._dinamo_zagreb |
| 436 | m45_motorway terminus_location | watford_gap | ✓ | ✓ |  |  |
| 437 | ramshir located_in_the_administrative_territorial_ | central_district | ✓ | ✓ |  |  |
| 438 | échassières located_in_time_zone | utc+01:00 | ✓ | ✓ |  |  |
| 439 | yaroslav_deda member_of_sports_team | fc_volyn_lutsk | ✓ | ✓ |  |  |
| 440 | john_collier languages_spoken,_written_or_signed | english | ✓ | ✓ |  |  |
| 441 | fernando_de_moraes member_of_sports_team | australia_national_futsal | ✓ | ✓ |  |  |
| 442 | trumaker_&_co. country | united_states_of_america | ✓ | ✓ |  |  |
| 443 | bernard_malamud notable_work | the_magic_barrel | ✗ | ✓ | ✓ SAVED | the_assistant |
| 444 | dunkirk,_nottingham country | united_kingdom | ✓ | ✓ |  |  |
| 445 | all_hands_on_deck part_of | aquarius | ✓ | ✓ |  |  |
| 446 | musō_soseki languages_spoken,_written_or_signed | japanese | ✓ | ✓ |  |  |
| 447 | return_of_the_living_dead_part_ii cast_member | james_karen | ✓ | ✓ |  |  |
| 448 | seven_men_from_now genre | western_film | ✓ | ✓ |  |  |
| 449 | patrick_m'boma given_name | patrick | ✓ | ✓ |  |  |
| 450 | æneas_mackenzie instance_of | human | ✓ | ✓ |  |  |
| 451 | northern_dancer color | bay | ✓ | ✓ |  |  |
| 452 | list_of_uk_r&b_singles_chart_number_ones_of_2016 i | wikimedia_list_article | ✓ | ✓ |  |  |
| 453 | harry_potter_and_the_order_of_the_phoenix filming_ | turkey | ✓ | ✓ |  |  |
| 454 | ng_eng_hen instance_of | human | ✓ | ✓ |  |  |
| 455 | joaquín_argamasilla given_name | joaquín | ✓ | ✓ |  |  |
| 456 | tim_castille member_of_sports_team | kansas_city_chiefs | ✓ | ✓ |  |  |
| 457 | gabriela_silang country_of_citizenship | philippines | ✓ | ✓ |  |  |
| 458 | blake_berris place_of_birth | los_angeles | ✓ | ✓ |  |  |
| 459 | mike_sandbothe employer | berlin_university_of_the_ | ✓ | ✓ |  |  |
| 460 | lincoln_mks powered_by | petrol_engine | ✓ | ✓ |  |  |
| 461 | tales_from_northumberland_with_robson_green countr | united_kingdom | ✓ | ✓ |  |  |
| 462 | 2015–16_isthmian_league sport | association_football | ✓ | ✓ |  |  |
| 463 | ramon_d'abadal_i_de_vinyals educated_at | university_of_barcelona | ✓ | ✓ |  |  |
| 464 | corsair country_of_origin | united_states_of_america | ✓ | ✓ |  |  |
| 465 | hybothecus_flohri instance_of | taxon | ✓ | ✓ |  |  |
| 466 | chilean_navy country | chile | ✓ | ✓ |  |  |
| 467 | tridens instance_of | taxon | ✓ | ✓ |  |  |
| 468 | sahar_youssef participant_of | 1984_summer_olympics | ✓ | ✓ |  |  |
| 469 | rhododendron_phaeochrysum parent_taxon | rhododendron | ✓ | ✓ |  |  |
| 470 | lesley_garrett voice_type | soprano | ✓ | ✓ |  |  |
| 471 | fort_franklin_battlespace_laboratory located_in_th | massachusetts | ✓ | ✓ |  |  |
| 472 | rafael_barbosa_do_nascimento sport | association_football | ✓ | ✓ |  |  |
| 473 | nikola_aksentijević member_of_sports_team | vitesse | ✓ | ✓ |  |  |
| 474 | 2017_tirreno–adriatico participating_team | bahrain-merida_2017 | ✓ | ✓ |  |  |
| 475 | ouray_mine instance_of | mine | ✓ | ✓ |  |  |
| 476 | code_of_the_outlaw country_of_origin | united_states_of_america | ✓ | ✓ |  |  |
| 477 | x_factor_georgia original_network | rustavi_2 | ✓ | ✓ |  |  |
| 478 | those_who_were_hung_hang_here followed_by | modern_currencies | ✗ | ✗ |  |  |
| 479 | anyamaru_tantei_kiruminzuu genre | shōjo | ✓ | ✓ |  |  |
| 480 | bouchaib_el_moubarki member_of_sports_team | al_ahli_sc | ✓ | ✓ |  |  |
| 481 | frits_zernike place_of_death | amersfoort | ✓ | ✓ |  |  |
| 482 | ashraf_choudhary place_of_birth | sialkot | ✓ | ✓ |  |  |
| 483 | david_grant sport | association_football | ✓ | ✓ |  |  |
| 484 | the_good_night cast_member | penélope_cruz | ✗ | ✓ | ✓ SAVED | martin_freeman |
| 485 | 1947_tour_de_france,_stage_1_to_stage_11 country | france | ✓ | ✓ |  |  |
| 486 | henry_stafford,_2nd_duke_of_buckingham child | elizabeth_stafford,_count | ✓ | ✓ |  |  |
| 487 | 2005–06_ligue_magnus_season country | france | ✓ | ✓ |  |  |
| 488 | province_of_messina contains_administrative_territ | reitano | ✗ | ✗ |  |  |
| 489 | evan_taylor member_of_sports_team | harbour_view_f.c. | ✓ | ✓ |  |  |
| 490 | christina_hengster languages_spoken,_written_or_si | german | ✓ | ✓ |  |  |
| 491 | malegoude shares_border_with | seignalens | ✓ | ✓ |  |  |
| 492 | magna_carta contributor(s)_to_the_creative_work_or | caroline_lucas | ✗ | ✗ |  |  |
| 493 | wilshire located_in_the_administrative_territorial | california | ✓ | ✓ |  |  |
| 494 | nemanja_miletić member_of_sports_team | fk_sloga_kraljevo | ✗ | ✓ | ✓ SAVED | fk_radnički_stobex |
| 495 | mainframe_sort_merge instance_of | software | ✓ | ✓ |  |  |
| 496 | harald_feller instance_of | human | ✓ | ✓ |  |  |
| 497 | steve_mcmanaman sport | association_football | ✓ | ✓ |  |  |
| 498 | max_speter given_name | max | ✓ | ✓ |  |  |
| 499 | gertrude_abercrombie employer | works_progress_administra | ✓ | ✓ |  |  |
| 500 | sriranjani occupation | actor | ✓ | ✓ |  |  |

---

## Mode 3 — Abductive Verification (500)

| # | Query | Gold | Direct Hit@5 | Reverse Query | Verified |
|---|-------|------|-------------|---------------|----------|
| 1 | edward_c._campbell occupation | judge | ✓ | judge | ✗ |
| 2 | y_felinheli instance_of | community | ✓ | community | ✗ |
| 3 | isher_judge_ahluwalia educated_at | massachusetts_institute_o | ✓ | massachusetts_institute_o | ✗ |
| 4 | foxa1 instance_of | gene | ✓ | gene | ✗ |
| 5 | ardentes shares_border_with | le_poinçonnet | ✓ | le_poinçonnet | ✗ |
| 6 | tristin_mays instance_of | human | ✓ | human | ✗ |
| 7 | héctor_jiménez occupation | film_producer | ✓ | film_producer | ✗ |
| 8 | otonica country | slovenia | ✓ | slovenia | ✗ |
| 9 | popeye genre | action_game | ✓ | action_game | ✗ |
| 10 | gray_marine_motor_company headquarters_location | detroit | ✓ | detroit | ✗ |
| 11 | shan_vincent_de_paul instance_of | human | ✓ | human | ✗ |
| 12 | the_big_town instance_of | short_film | ✓ | short_film | ✗ |
| 13 | 1944_cleveland_rams_season sport | american_football | ✓ | american_football | ✗ |
| 14 | falborek located_in_time_zone | utc+01:00 | ✓ | utc+01:00 | ✗ |
| 15 | ernest_champion member_of_sports_team | charlton_athletic_f.c. | ✓ | charlton_athletic_f.c. | ✗ |
| 16 | edward_boustead place_of_birth | yorkshire | ✓ | yorkshire | ✗ |
| 17 | m38_wolfhound instance_of | armored_car | ✓ | armored_car | ✗ |
| 18 | krang present_in_work | teenage_mutant_ninja_turt | ✓ | teenage_mutant_ninja_turt | ✗ |
| 19 | blind_man's_bluff instance_of | film | ✓ | film | ✗ |
| 20 | ciini instance_of | taxon | ✓ | taxon | ✗ |
| 21 | shameless country_of_origin | germany | ✓ | germany | ✗ |
| 22 | bazar_house_in_miłosław located_in_the_administrat | miłosław | ✓ | miłosław | ✗ |
| 23 | bill_bailey given_name | bill | ✓ | bill | ✗ |
| 24 | helene_weber country_of_citizenship | germany | ✓ | germany | ✗ |
| 25 | franz_von_seitz given_name | franz | ✓ | franz | ✗ |
| 26 | hugh_hefner:_playboy,_activist_and_rebel cast_memb | jenny_mccarthy | ✓ | jenny_mccarthy | ✗ |
| 27 | george_anderson place_of_death | canada | ✓ | canada | ✗ |
| 28 | laynce_nix handedness | left-handedness | ✓ | left-handedness | ✗ |
| 29 | piano instance_of | play | ✓ | play | ✗ |
| 30 | roman_bagration country_of_citizenship | georgia | ✓ | georgia | ✗ |
| 31 | united_nations_security_council_resolution_551 ins | united_nations_security_c | ✓ | united_nations_security_c | ✗ |
| 32 | gustav_flatow place_of_death | theresienstadt_concentrat | ✓ | theresienstadt_concentrat | ✗ |
| 33 | ron_white occupation | songwriter | ✓ | songwriter | ✗ |
| 34 | karin_kschwendt country_of_citizenship | austria | ✓ | austria | ✗ |
| 35 | urubamba_mountain_range country | peru | ✓ | peru | ✗ |
| 36 | written_language opposite_of | spoken_language | ✓ | spoken_language | ✗ |
| 37 | stefanowo,_masovian_voivodeship located_in_time_zo | utc+02:00 | ✓ | utc+02:00 | ✗ |
| 38 | choreutis_achyrodes taxon_rank | species | ✓ | species | ✗ |
| 39 | sigeberht instance_of | human | ✓ | human | ✗ |
| 40 | francesco_bracciolini occupation | writer | ✓ | writer | ✗ |
| 41 | shine,_shine,_my_star genre | grotto-esque | ✓ | grotto-esque | ✗ |
| 42 | premam composer | gopi_sundar | ✓ | gopi_sundar | ✗ |
| 43 | honghuli_station instance_of | metro_station | ✓ | metro_station | ✗ |
| 44 | porrera shares_border_with | poboleda | ✗ |  | — |
| 45 | george_r._johnson instance_of | human | ✓ | human | ✗ |
| 46 | ludmilla_of_bohemia spouse | louis_i | ✓ | louis_i | ✗ |
| 47 | canty_bay instance_of | hamlet | ✓ | hamlet | ✗ |
| 48 | halston cause_of_death | cancer | ✓ | cancer | ✗ |
| 49 | hans_wilhelm_frei award_received | john_simon_guggenheim_mem | ✓ | john_simon_guggenheim_mem | ✗ |
| 50 | the_little_thief director | claude_miller | ✓ | claude_miller | ✗ |
| 51 | mydas_luteipennis parent_taxon | mydas | ✓ | mydas | ✗ |
| 52 | tere_glassie instance_of | human | ✓ | human | ✗ |
| 53 | jordi_puigneró_i_ferrer instance_of | human | ✓ | human | ✗ |
| 54 | pedro_colón member_of_political_party | democratic_party | ✓ | democratic_party | ✗ |
| 55 | schnals located_in_time_zone | utc+01:00 | ✓ | utc+01:00 | ✗ |
| 56 | human_resources_university instance_of | university | ✓ | university | ✗ |
| 57 | general_post_office located_in_the_administrative_ | queensland | ✓ | queensland | ✗ |
| 58 | euphemia_of_rügen instance_of | human | ✓ | human | ✗ |
| 59 | antikensammlung_berlin instance_of | art_collection | ✓ | art_collection | ✗ |
| 60 | château_de_cléron located_in_the_administrative_te | cléron | ✓ | cléron | ✗ |
| 61 | rescue_nunatak instance_of | mountain | ✓ | mountain | ✗ |
| 62 | vukašin_jovanović member_of_sports_team | serbia_national_under-19_ | ✓ | serbia_national_under-19_ | ✗ |
| 63 | my_losing_season publisher | nan_a._talese | ✓ | nan_a._talese | ✗ |
| 64 | australian_derby country | australia | ✓ | australia | ✗ |
| 65 | helmut_kremers member_of_sports_team | germany_national_football | ✓ | germany_national_football | ✗ |
| 66 | alyaksandr_alhavik member_of_sports_team | fc_khimik_svetlogorsk | ✓ | fc_khimik_svetlogorsk | ✗ |
| 67 | gornje_gare located_in_time_zone | utc+01:00 | ✓ | utc+01:00 | ✗ |
| 68 | canton_of_jarnages contains_administrative_territo | saint-silvain-sous-toulx | ✗ |  | — |
| 69 | 1983_virginia_slims_of_washington_–_singles winner | martina_navratilova | ✓ | martina_navratilova | ✗ |
| 70 | ross_bentley country_of_citizenship | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 71 | neuroscientist field_of_this_occupation | neuroscience | ✓ | neuroscience | ✗ |
| 72 | sucha_struga located_in_time_zone | utc+01:00 | ✓ | utc+01:00 | ✗ |
| 73 | beauty_and_the_beast significant_event | première | ✓ | première | ✗ |
| 74 | wilkins_highway country | australia | ✓ | australia | ✗ |
| 75 | girl_in_the_cadillac cast_member | william_shockley | ✗ |  | — |
| 76 | jeziorki,_świecie_county located_in_the_administra | gmina_lniano | ✓ | gmina_lniano | ✗ |
| 77 | kaitō_royale country_of_origin | japan | ✓ | japan | ✗ |
| 78 | fayette_high_school located_in_the_administrative_ | ohio | ✓ | ohio | ✗ |
| 79 | brice_dja_djédjé member_of_sports_team | olympique_de_marseille | ✓ | olympique_de_marseille | ✗ |
| 80 | dhunni instance_of | union_council_of_pakistan | ✓ | union_council_of_pakistan | ✗ |
| 81 | 1991_asian_women's_handball_championship instance_ | asian_women's_handball_ch | ✓ | asian_women's_handball_ch | ✗ |
| 82 | the_lost_take record_label | anticon. | ✓ | anticon. | ✗ |
| 83 | curtner country | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 84 | chemical_heart part_of | new_detention | ✓ | new_detention | ✗ |
| 85 | dermacentor_circumguttatus taxon_rank | species | ✓ | species | ✗ |
| 86 | daniel_avery place_of_birth | groton | ✓ | groton | ✗ |
| 87 | mansfield located_in_the_administrative_territoria | desoto_parish | ✗ |  | — |
| 88 | clinton_solomon instance_of | human | ✓ | human | ✗ |
| 89 | the_evolution_of_gospel performer | sounds_of_blackness | ✓ | sounds_of_blackness | ✗ |
| 90 | joel_feeney place_of_birth | oakville | ✓ | oakville | ✗ |
| 91 | shareef_adnan member_of_sports_team | shabab_al-ordon_club | ✓ | shabab_al-ordon_club | ✗ |
| 92 | shadiwal_hydropower_plant instance_of | hydroelectric_power_stati | ✓ | hydroelectric_power_stati | ✗ |
| 93 | national_cycle_route_75 instance_of | long-distance_cycling_rou | ✓ | long-distance_cycling_rou | ✗ |
| 94 | det_gælder_os_alle genre | drama_film | ✓ | drama_film | ✗ |
| 95 | upplanda located_in_time_zone | utc+02:00 | ✓ | utc+02:00 | ✗ |
| 96 | south_pasadena_unified_school_district located_in_ | california | ✓ | california | ✗ |
| 97 | karl_brunner given_name | karl | ✓ | karl | ✗ |
| 98 | rehoboth_ratepayers'_association headquarters_loca | rehoboth | ✓ | rehoboth | ✗ |
| 99 | 2012_thai_division_1_league sports_season_of_leagu | thai_division_1_league | ✓ | thai_division_1_league | ✗ |
| 100 | georges_semichon given_name | george | ✓ | george | ✗ |
| 101 | baphia_puguensis iucn_conservation_status | endangered_species | ✓ | endangered_species | ✗ |
| 102 | al_son_de_la_marimba cast_member | sara_garcía | ✓ | sara_garcía | ✗ |
| 103 | cary_brothers country_of_citizenship | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 104 | thomas_fitzgibbon_moore instance_of | human | ✓ | human | ✗ |
| 105 | anthony_cooke given_name | anthony | ✓ | anthony | ✗ |
| 106 | richard_williams educated_at | mississippi_state_univers | ✓ | mississippi_state_univers | ✗ |
| 107 | simone_le_bargy occupation | actor | ✓ | actor | ✗ |
| 108 | avengers:_infinity_war cast_member | paul_bettany | ✗ |  | — |
| 109 | antipas_of_pergamum country_of_citizenship | ancient_rome | ✓ | ancient_rome | ✗ |
| 110 | between_friends cast_member | lou_tellegen | ✓ | lou_tellegen | ✗ |
| 111 | the_age_of_adaline cast_member | harrison_ford | ✗ |  | — |
| 112 | list_of_first_ladies_of_cameroon is_a_list_of | person | ✓ | person | ✗ |
| 113 | auzeville-tolosane shares_border_with | pechbusque | ✓ | pechbusque | ✗ |
| 114 | eudonia_australialis parent_taxon | eudonia | ✓ | eudonia | ✗ |
| 115 | cass_building architect | smithgroup | ✓ | smithgroup | ✗ |
| 116 | jan_kmenta employer | university_of_michigan | ✓ | university_of_michigan | ✗ |
| 117 | paul_freeman educated_at | eastman_school_of_music | ✓ | eastman_school_of_music | ✗ |
| 118 | karin_söder instance_of | human | ✓ | human | ✗ |
| 119 | the_mice cast_member | henry_silva | ✓ | henry_silva | ✗ |
| 120 | tomás_herrera_martínez participant_of | 1972_summer_olympics | ✓ | 1972_summer_olympics | ✗ |
| 121 | james_pritchard instance_of | human | ✓ | human | ✗ |
| 122 | 1280_in_poetry facet_of | poetry | ✓ | poetry | ✗ |
| 123 | somatina_accraria instance_of | taxon | ✓ | taxon | ✗ |
| 124 | paul_massey instance_of | human | ✓ | human | ✗ |
| 125 | pyrausta_sanguinalis taxon_rank | species | ✓ | species | ✗ |
| 126 | snuggle_truck game_mode | single-player_video_game | ✓ | single-player_video_game | ✗ |
| 127 | frederick_fitzclarence given_name | frederick | ✓ | frederick | ✗ |
| 128 | michael_cartellone instrument | drum_kit | ✓ | drum_kit | ✗ |
| 129 | niphoparmena_latifrons parent_taxon | niphoparmena | ✓ | niphoparmena | ✗ |
| 130 | cité_du_niger country | mali | ✓ | mali | ✗ |
| 131 | tsarevich_dmitry_alexeyevich_of_russia sibling | sophia_alekseyevna_of_rus | ✗ |  | — |
| 132 | dancing_in_water cast_member | petar_banićević | ✗ |  | — |
| 133 | echunga country | australia | ✓ | australia | ✗ |
| 134 | nesoptilotis instance_of | taxon | ✓ | taxon | ✗ |
| 135 | maximilian,_crown_prince_of_saxony sibling | princess_maria_amalia_of_ | ✓ | princess_maria_amalia_of_ | ✗ |
| 136 | 2013_tatarstan_open_–_doubles sport | tennis | ✓ | tennis | ✗ |
| 137 | the_day_of_the_owl language_of_work_or_name | italian | ✓ | italian | ✗ |
| 138 | catch_me_if_you_can instance_of | album | ✗ |  | — |
| 139 | oleszki located_in_the_administrative_territorial_ | gmina_busko-zdrój | ✓ | gmina_busko-zdrój | ✗ |
| 140 | johann_christian_von_stramberg occupation | historian | ✓ | historian | ✗ |
| 141 | denis_kapochkin member_of_sports_team | fc_nara-shbfr_naro-fomins | ✓ | fc_nara-shbfr_naro-fomins | ✗ |
| 142 | brad_isbister instance_of | human | ✓ | human | ✗ |
| 143 | phaethontidae parent_taxon | phaethontiformes | ✓ | phaethontiformes | ✗ |
| 144 | the_house_of_the_seven_gables production_designer | jack_otterson | ✓ | jack_otterson | ✗ |
| 145 | dean_of_ferns instance_of | wikimedia_list_article | ✓ | wikimedia_list_article | ✗ |
| 146 | propilidium_pertenue taxon_rank | species | ✓ | species | ✗ |
| 147 | br.1050_alizé armament | depth_charge | ✓ | depth_charge | ✗ |
| 148 | olbrachcice,_masovian_voivodeship located_in_time_ | utc+02:00 | ✓ | utc+02:00 | ✗ |
| 149 | gega_diasamidze occupation | association_football_play | ✓ | association_football_play | ✗ |
| 150 | patinoire_de_malley owned_by | prilly | ✓ | prilly | ✗ |
| 151 | aleksey_petrovich_yermolov conflict | napoleonic_wars | ✓ | napoleonic_wars | ✗ |
| 152 | i_hate_you_now... genre | pop_music | ✓ | pop_music | ✗ |
| 153 | nanda_devi_national_park heritage_designation | unesco_world_heritage_sit | ✓ | unesco_world_heritage_sit | ✗ |
| 154 | buldhana_vidhan_sabha_constituency country | india | ✓ | india | ✗ |
| 155 | camden_airstrip instance_of | airport | ✓ | airport | ✗ |
| 156 | university_of_california,_irvine has_part | school_of_education | ✗ |  | — |
| 157 | mühlanger country | germany | ✓ | germany | ✗ |
| 158 | ștefan_cel_mare located_in_the_administrative_terr | neamț_county | ✓ | neamț_county | ✗ |
| 159 | michael_f._guyer instance_of | human | ✓ | human | ✗ |
| 160 | volume_1:_65's.late.nite.double-a-side.college.cut | album | ✓ | album | ✗ |
| 161 | far_cry producer | nick_raskulinecz | ✓ | nick_raskulinecz | ✗ |
| 162 | pilocrocis_cuprescens parent_taxon | pilocrocis | ✓ | pilocrocis | ✗ |
| 163 | hughie_dow member_of_sports_team | sunderland_a.f.c. | ✓ | sunderland_a.f.c. | ✗ |
| 164 | adalbert_iii_of_saxony sibling | margaret_of_saxony,_duche | ✓ | margaret_of_saxony,_duche | ✗ |
| 165 | george_herbert,_8th_earl_of_carnarvon educated_at | eton_college | ✓ | eton_college | ✗ |
| 166 | benjamin_heywood languages_spoken,_written_or_sign | english | ✓ | english | ✗ |
| 167 | tashkent_mechanical_plant instance_of | business | ✓ | business | ✗ |
| 168 | jealous record_label | parlophone | ✓ | parlophone | ✗ |
| 169 | valentin_bădoi position_played_on_team | midfielder | ✓ | midfielder | ✗ |
| 170 | bright_lights:_starring_carrie_fisher_and_debbie_r | debbie_reynolds | ✓ | debbie_reynolds | ✗ |
| 171 | ace_of_aces producer | horst_wendlandt | ✓ | horst_wendlandt | ✗ |
| 172 | gennaro_fragiello member_of_sports_team | a.c._carpenedolo | ✗ |  | — |
| 173 | tiago_jonas place_of_birth | porto | ✓ | porto | ✗ |
| 174 | le_lyrial instance_of | cruise_ship | ✓ | cruise_ship | ✗ |
| 175 | knut_johannesen country_of_citizenship | norway | ✓ | norway | ✗ |
| 176 | marco_airosa member_of_sports_team | angola_national_football_ | ✗ |  | — |
| 177 | james_vasquez instance_of | human | ✓ | human | ✗ |
| 178 | kaklamanis writing_system | greek_alphabet | ✓ | greek_alphabet | ✗ |
| 179 | harold_huntley_bassett occupation | military_officer | ✓ | military_officer | ✗ |
| 180 | red_rock_bridge instance_of | bridge | ✓ | bridge | ✗ |
| 181 | sebastian_praus languages_spoken,_written_or_signe | german | ✓ | german | ✗ |
| 182 | franjo_džidić member_of_sports_team | nk_široki_brijeg | ✓ | nk_široki_brijeg | ✗ |
| 183 | margherita_d'anjou librettist | felice_romani | ✓ | felice_romani | ✗ |
| 184 | villa_melnik_winery headquarters_location | harsovo,_blagoevgrad_prov | ✓ | harsovo,_blagoevgrad_prov | ✗ |
| 185 | jamie_rauch place_of_birth | houston | ✓ | houston | ✗ |
| 186 | pekka_sylvander participant_of | 1964_summer_olympics | ✓ | 1964_summer_olympics | ✗ |
| 187 | female_agents cast_member | xavier_beauvois | ✓ | xavier_beauvois | ✗ |
| 188 | yvelines contains_administrative_territorial_entit | le_mesnil-le-roi | ✗ |  | — |
| 189 | vince_clarke bowling_style | leg_break | ✓ | leg_break | ✗ |
| 190 | ashley_graham country_of_citizenship | australia | ✓ | australia | ✗ |
| 191 | dreams_awake country_of_origin | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 192 | sharove country | albania | ✓ | albania | ✗ |
| 193 | men_without_a_fatherland cast_member | willi_schaeffers | ✗ |  | — |
| 194 | israel_national_basketball_team instance_of | national_sports_team | ✓ | national_sports_team | ✗ |
| 195 | françois-louis_français described_by_source | brockhaus_and_efron_encyc | ✓ | brockhaus_and_efron_encyc | ✗ |
| 196 | kabile_island instance_of | island | ✓ | island | ✗ |
| 197 | conceptual_party_unity political_ideology | stalinism | ✓ | stalinism | ✗ |
| 198 | davy_schollen member_of_sports_team | k.r.c._genk | ✓ | k.r.c._genk | ✗ |
| 199 | robot_entertainment country | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 200 | armands_zeiberliņš member_of_sports_team | ope_if | ✗ |  | — |
| 201 | carl_jung significant_person | sigmund_freud | ✓ | sigmund_freud | ✗ |
| 202 | red-shouldered_vanga parent_taxon | calicalicus | ✓ | calicalicus | ✗ |
| 203 | the_secret_war country_of_origin | united_kingdom | ✓ | united_kingdom | ✗ |
| 204 | liebfrauen,_frankfurt located_in_the_administrativ | frankfurt | ✓ | frankfurt | ✗ |
| 205 | choi_min-ho given_name | min-ho | ✓ | min-ho | ✗ |
| 206 | 1999_segunda_división_peruana instance_of | sports_season | ✓ | sports_season | ✗ |
| 207 | extra_space_storage headquarters_location | cottonwood_heights | ✓ | cottonwood_heights | ✗ |
| 208 | noel_hunt position_played_on_team | forward | ✓ | forward | ✗ |
| 209 | kalmakanda_upazila country | bangladesh | ✓ | bangladesh | ✗ |
| 210 | baillif shares_border_with | basse-terre | ✓ | basse-terre | ✗ |
| 211 | rayappanur country | india | ✓ | india | ✗ |
| 212 | haute-marne contains_administrative_territorial_en | vaudrémont | ✗ |  | — |
| 213 | carlos_turrubiates position_played_on_team | defender | ✓ | defender | ✗ |
| 214 | nevin_william_hayes instance_of | human | ✓ | human | ✗ |
| 215 | john_gillespie member_of_sports_team | scotland_national_rugby_u | ✓ | scotland_national_rugby_u | ✗ |
| 216 | john_george_walker place_of_birth | jefferson_city | ✓ | jefferson_city | ✗ |
| 217 | maumee-class_oiler followed_by | usns_american_explorer | ✓ | usns_american_explorer | ✗ |
| 218 | vullnet_basha member_of_sports_team | grasshopper_club_zürich | ✓ | grasshopper_club_zürich | ✗ |
| 219 | ray_ozzie educated_at | university_of_illinois_sy | ✓ | university_of_illinois_sy | ✗ |
| 220 | katharine_ross spouse | sam_elliott | ✓ | sam_elliott | ✗ |
| 221 | sringaram cast_member | aditi_rao_hydari | ✓ | aditi_rao_hydari | ✗ |
| 222 | pacific_leaping_blenny parent_taxon | alticus | ✓ | alticus | ✗ |
| 223 | shake_your_rump followed_by | johnny_ryall | ✓ | johnny_ryall | ✗ |
| 224 | jenny_valentine educated_at | goldsmiths,_university_of | ✓ | goldsmiths,_university_of | ✗ |
| 225 | siddharth_gupta instance_of | human | ✓ | human | ✗ |
| 226 | 1990–91_leicester_city_f.c._season sport | association_football | ✓ | association_football | ✗ |
| 227 | sailors'_snug_harbor part_of | new_york_city_subway | ✓ | new_york_city_subway | ✗ |
| 228 | the_foreman_of_the_jury cast_member | roscoe_arbuckle | ✓ | roscoe_arbuckle | ✗ |
| 229 | anno_2205 instance_of | video_game | ✓ | video_game | ✗ |
| 230 | private_confessions cast_member | hans_alfredson | ✗ |  | — |
| 231 | boy_trouble color | black-and-white | ✓ | black-and-white | ✗ |
| 232 | chester_ray_benjamin educated_at | university_of_iowa | ✓ | university_of_iowa | ✗ |
| 233 | creature instance_of | studio_album | ✗ |  | — |
| 234 | angus_maclaine instance_of | human | ✓ | human | ✗ |
| 235 | the_slammin'_salmon cast_member | cobie_smulders | ✗ |  | — |
| 236 | i'm_going_home_to_dixie instance_of | song | ✓ | song | ✗ |
| 237 | archinform instance_of | encyclopedia | ✓ | encyclopedia | ✗ |
| 238 | carry_on..._up_the_khyber country_of_origin | united_kingdom | ✓ | united_kingdom | ✗ |
| 239 | king_abdullah_design_and_development_bureau headqu | amman | ✓ | amman | ✗ |
| 240 | dorfstetten located_in_time_zone | utc+02:00 | ✓ | utc+02:00 | ✗ |
| 241 | universitas_psychologica publisher | pontifical_xavierian_univ | ✓ | pontifical_xavierian_univ | ✗ |
| 242 | yevhen_drahunov place_of_birth | makiivka | ✓ | makiivka | ✗ |
| 243 | julius_caesar award_received | golden_leopard | ✓ | golden_leopard | ✗ |
| 244 | andrei_sidorenkov member_of_sports_team | viljandi_jk_tulevik | ✗ |  | — |
| 245 | bob_perry member_of_sports_team | fall_river_marksmen | ✓ | fall_river_marksmen | ✗ |
| 246 | mitch_glazer spouse | kelly_lynch | ✓ | kelly_lynch | ✗ |
| 247 | amirabad,_faruj country | iran | ✓ | iran | ✗ |
| 248 | são_mamede country | portugal | ✓ | portugal | ✗ |
| 249 | holley_central_school_district located_in_the_admi | new_york | ✓ | new_york | ✗ |
| 250 | es_migjorn_gran located_in_or_next_to_body_of_wate | mediterranean_sea | ✓ | mediterranean_sea | ✗ |
| 251 | baby_blue_marine director | john_d._hancock | ✓ | john_d._hancock | ✗ |
| 252 | aeromonas_fluvialis parent_taxon | aeromonas | ✓ | aeromonas | ✗ |
| 253 | bhairava_dweepam country_of_origin | india | ✓ | india | ✗ |
| 254 | leon_mettam instance_of | human | ✓ | human | ✗ |
| 255 | dean_collis country_of_citizenship | australia | ✓ | australia | ✗ |
| 256 | list_of_libraries_in_the_palestinian_territories s | list_of_libraries_by_coun | ✓ | list_of_libraries_by_coun | ✗ |
| 257 | now_that's_what_i_call_music!_52 record_label | virgin_records | ✗ |  | — |
| 258 | heine_meine country_of_citizenship | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 259 | epacris_calvertiana taxon_rank | species | ✓ | species | ✗ |
| 260 | valea_neagră_river country | romania | ✓ | romania | ✗ |
| 261 | kwns located_in_the_administrative_territorial_ent | texas | ✓ | texas | ✗ |
| 262 | north_african_ostrich taxon_rank | subspecies | ✓ | subspecies | ✗ |
| 263 | rex_hudson country_of_citizenship | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 264 | świerzowa_polska located_in_time_zone | utc+01:00 | ✓ | utc+01:00 | ✗ |
| 265 | besalampy_airport instance_of | airport | ✓ | airport | ✗ |
| 266 | flag_of_rwanda color | blue | ✓ | blue | ✗ |
| 267 | mark_robinson place_of_birth | belfast | ✗ |  | — |
| 268 | james_gamble member_of_political_party | democratic_party | ✓ | democratic_party | ✗ |
| 269 | simone_assemani place_of_death | padua | ✓ | padua | ✗ |
| 270 | tunde_ke_kabab country_of_origin | india | ✓ | india | ✗ |
| 271 | kunihiro_hasegawa given_name | kunihiro | ✓ | kunihiro | ✗ |
| 272 | st_nectan's_church,_hartland named_after | nectan_of_hartland | ✓ | nectan_of_hartland | ✗ |
| 273 | 2017_open_bnp_paribas_banque_de_bretagne_–_singles | tennis | ✓ | tennis | ✗ |
| 274 | bathytoma_murdochi instance_of | taxon | ✓ | taxon | ✗ |
| 275 | princess_lalla_meryem_of_morocco sibling | hasna_of_morocco | ✓ | hasna_of_morocco | ✗ |
| 276 | tyne_valley-linkletter located_in_the_administrati | prince_edward_island | ✓ | prince_edward_island | ✗ |
| 277 | aretas_akers-douglas,_2nd_viscount_chilston place_ | kent | ✓ | kent | ✗ |
| 278 | agua_mala part_of | the_x-files,_season_6 | ✓ | the_x-files,_season_6 | ✗ |
| 279 | jean_thomas_guillaume_lorge place_of_death | chauconin-neufmontiers | ✓ | chauconin-neufmontiers | ✗ |
| 280 | irmgard_griss occupation | politician | ✓ | politician | ✗ |
| 281 | guynesomia instance_of | taxon | ✓ | taxon | ✗ |
| 282 | sun_longjiang participant_of | 2010_winter_olympics | ✓ | 2010_winter_olympics | ✗ |
| 283 | keena_turner country_of_citizenship | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 284 | fiery-capped_manakin taxon_rank | species | ✓ | species | ✗ |
| 285 | hyatt_place_waikiki_beach country | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 286 | johann_gotthard_von_müller instance_of | human | ✓ | human | ✗ |
| 287 | czechoslovakia head_of_state | václav_havel | ✓ | václav_havel | ✗ |
| 288 | heinrich_nickel country_of_citizenship | germany | ✓ | germany | ✗ |
| 289 | beyond_the_law cast_member | charlie_sheen | ✓ | charlie_sheen | ✗ |
| 290 | placogobio parent_taxon | cyprinidae | ✓ | cyprinidae | ✗ |
| 291 | somerville_college part_of | university_of_oxford | ✓ | university_of_oxford | ✗ |
| 292 | il_profeta cast_member | liana_orfei | ✓ | liana_orfei | ✗ |
| 293 | jhouwa_guthi located_in_time_zone | utc+05:45 | ✓ | utc+05:45 | ✗ |
| 294 | death_in_five_boxes country_of_origin | united_kingdom | ✓ | united_kingdom | ✗ |
| 295 | art_schwind place_of_death | sullivan | ✓ | sullivan | ✗ |
| 296 | kurt_ploeger given_name | kurt | ✓ | kurt | ✗ |
| 297 | pleven_province contains_administrative_territoria | pleven_municipality | ✗ |  | — |
| 298 | paddy_mclaughlin member_of_sports_team | harrogate_town_a.f.c. | ✓ | harrogate_town_a.f.c. | ✗ |
| 299 | ché_ahn country_of_citizenship | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 300 | wolfgang_wolf member_of_sports_team | stuttgarter_kickers | ✓ | stuttgarter_kickers | ✗ |
| 301 | stand_tall cast_member | arnold_schwarzenegger | ✓ | arnold_schwarzenegger | ✗ |
| 302 | splendrillia_woodringi taxon_rank | species | ✓ | species | ✗ |
| 303 | sutton_hall architect | cass_gilbert | ✓ | cass_gilbert | ✗ |
| 304 | control cast_member | michelle_rodriguez | ✗ |  | — |
| 305 | danièle_sallenave occupation | journalist | ✓ | journalist | ✗ |
| 306 | kieron_barry instance_of | human | ✓ | human | ✗ |
| 307 | paulo_césar_arruda_parente member_of_sports_team | fluminense_f.c. | ✓ | fluminense_f.c. | ✗ |
| 308 | lucas_thwala member_of_sports_team | supersport_united_f.c. | ✓ | supersport_united_f.c. | ✗ |
| 309 | frank_killam instance_of | human | ✓ | human | ✗ |
| 310 | encore..._for_future_generations language_of_work_ | english | ✓ | english | ✗ |
| 311 | luke_sikma country_of_citizenship | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 312 | joel_carroll participant_of | 2012_summer_olympics | ✓ | 2012_summer_olympics | ✗ |
| 313 | ottmar_edenhofer occupation | economist | ✓ | economist | ✗ |
| 314 | new_riegel_high_school instance_of | state_school | ✓ | state_school | ✗ |
| 315 | david_sánchez_parrilla place_of_birth | tarragona | ✓ | tarragona | ✗ |
| 316 | patrick_zelbel country_of_citizenship | germany | ✓ | germany | ✗ |
| 317 | andrés_roa instance_of | human | ✓ | human | ✗ |
| 318 | insurial instance_of | business | ✓ | business | ✗ |
| 319 | john_holmstrom occupation | cartoonist | ✓ | cartoonist | ✗ |
| 320 | neola_semiaurata taxon_rank | species | ✓ | species | ✗ |
| 321 | kufra instance_of | oasis | ✓ | oasis | ✗ |
| 322 | cecily_mary_wise_pickerill occupation | surgeon | ✓ | surgeon | ✗ |
| 323 | john_treacher instance_of | human | ✓ | human | ✗ |
| 324 | thomas_a._swayze,_jr. place_of_birth | tacoma | ✓ | tacoma | ✗ |
| 325 | nuclear_weapons_convention instance_of | treaty | ✓ | treaty | ✗ |
| 326 | jamil_azzaoui given_name | jamil | ✓ | jamil | ✗ |
| 327 | rgs11 chromosome | human_chromosome_16 | ✓ | human_chromosome_16 | ✗ |
| 328 | seo_district instance_of | district_of_south_korea | ✓ | district_of_south_korea | ✗ |
| 329 | belarus–russia_border country | belarus | ✓ | belarus | ✗ |
| 330 | les_carter instance_of | human | ✓ | human | ✗ |
| 331 | time shares_border_with | hå | ✓ | hå | ✗ |
| 332 | priseltsi,_varna_province located_in_time_zone | utc+02:00 | ✓ | utc+02:00 | ✗ |
| 333 | confessions_of_an_english_opium-eater language_of_ | english | ✓ | english | ✗ |
| 334 | claude_delay given_name | claude | ✓ | claude | ✗ |
| 335 | fis_ski-flying_world_championships_1977 sport | ski_jumping | ✓ | ski_jumping | ✗ |
| 336 | trudy_silver instance_of | human | ✓ | human | ✗ |
| 337 | victor_lustig instance_of | human | ✓ | human | ✗ |
| 338 | oscar_fernández participant_of | 1996_summer_olympics | ✓ | 1996_summer_olympics | ✗ |
| 339 | george_p._fletcher country_of_citizenship | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 340 | william_howard_taft employer | yale_law_school | ✓ | yale_law_school | ✗ |
| 341 | william_cullen,_baron_cullen_of_whitekirk educated | university_of_edinburgh | ✓ | university_of_edinburgh | ✗ |
| 342 | kenni_fisilau member_of_sports_team | plymouth_albion_r.f.c. | ✓ | plymouth_albion_r.f.c. | ✗ |
| 343 | yasmine_pahlavi country_of_citizenship | iran | ✓ | iran | ✗ |
| 344 | rodnay_zaks field_of_work | computer_science | ✓ | computer_science | ✗ |
| 345 | ben_cauchi occupation | photographer | ✓ | photographer | ✗ |
| 346 | 2015_afghan_premier_league instance_of | sports_season | ✓ | sports_season | ✗ |
| 347 | monark_starstalker from_fictional_universe | marvel_universe | ✓ | marvel_universe | ✗ |
| 348 | bernhard_von_langenbeck given_name | bernhard | ✓ | bernhard | ✗ |
| 349 | tony_denman instance_of | human | ✓ | human | ✗ |
| 350 | niels_helveg_petersen position_held | minister_of_economic_and_ | ✓ | minister_of_economic_and_ | ✗ |
| 351 | petite_formation instance_of | formation | ✓ | formation | ✗ |
| 352 | la_odalisca_no._13 country_of_origin | mexico | ✓ | mexico | ✗ |
| 353 | who's_harry_crumb? genre | comedy_film | ✓ | comedy_film | ✗ |
| 354 | olympiakos_nicosia_fc participant_of | 1951–52_cypriot_first_div | ✗ |  | — |
| 355 | deep_thought sport | chess | ✓ | chess | ✗ |
| 356 | reginald_wynn_owen instance_of | human | ✓ | human | ✗ |
| 357 | bill_white member_of_sports_team | newport_county_a.f.c. | ✗ |  | — |
| 358 | burmese_american instance_of | ethnic_group | ✓ | ethnic_group | ✗ |
| 359 | university_of_calgary_faculty_of_arts located_in_t | calgary | ✓ | calgary | ✗ |
| 360 | smarcc1 found_in_taxon | homo_sapiens | ✓ | homo_sapiens | ✗ |
| 361 | dermival_almeida_lima member_of_sports_team | brasiliense_futebol_clube | ✗ |  | — |
| 362 | megachile_digna instance_of | taxon | ✓ | taxon | ✗ |
| 363 | grzegorz_tkaczyk member_of_sports_team | pge_vive_kielce | ✓ | pge_vive_kielce | ✗ |
| 364 | a-1_pictures instance_of | animation_studio | ✓ | animation_studio | ✗ |
| 365 | ipoh country | malaysia | ✓ | malaysia | ✗ |
| 366 | kees_van_ierssel instance_of | human | ✓ | human | ✗ |
| 367 | il_gatto cast_member | mariangela_melato | ✗ |  | — |
| 368 | tentax_bruneii taxon_rank | species | ✓ | species | ✗ |
| 369 | poison_ivy country_of_origin | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 370 | oktyabr' country | kyrgyzstan | ✓ | kyrgyzstan | ✗ |
| 371 | uss_darke country | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 372 | vincent_moscaritolo occupation | engineer | ✓ | engineer | ✗ |
| 373 | 20_dakika original_language_of_film_or_tv_show | turkish | ✓ | turkish | ✗ |
| 374 | city_of_tiny_lights distributor | icon_productions | ✓ | icon_productions | ✗ |
| 375 | elkin_blanco occupation | association_football_play | ✓ | association_football_play | ✗ |
| 376 | steve_adams member_of_sports_team | swindon_town_f.c. | ✗ |  | — |
| 377 | billy_bibby_&_the_wry_smiles genre | rock_music | ✓ | rock_music | ✗ |
| 378 | the_famous_jett_jackson cast_member | ryan_sommers_baum | ✓ | ryan_sommers_baum | ✗ |
| 379 | hans_rudi_erdt instance_of | human | ✓ | human | ✗ |
| 380 | küttigen country | switzerland | ✓ | switzerland | ✗ |
| 381 | mindanao_miniature_babbler iucn_conservation_statu | data_deficient | ✓ | data_deficient | ✗ |
| 382 | disappear producer | howard_benson | ✓ | howard_benson | ✗ |
| 383 | the_winding_stair cast_member | alma_rubens | ✓ | alma_rubens | ✗ |
| 384 | john_boorman instance_of | human | ✓ | human | ✗ |
| 385 | yankee_in_oz follows | merry_go_round_in_oz | ✓ | merry_go_round_in_oz | ✗ |
| 386 | 1830_united_kingdom_general_election follows | 1826_united_kingdom_gener | ✓ | 1826_united_kingdom_gener | ✗ |
| 387 | makita_ka_lang_muli original_language_of_film_or_t | filipino | ✓ | filipino | ✗ |
| 388 | burton_latimer twinned_administrative_body | castelnuovo_magra | ✓ | castelnuovo_magra | ✗ |
| 389 | matt_darey record_label | armada_music | ✓ | armada_music | ✗ |
| 390 | jamy,_lublin_voivodeship located_in_time_zone | utc+01:00 | ✓ | utc+01:00 | ✗ |
| 391 | sir_robert_ferguson,_2nd_baronet languages_spoken, | english | ✓ | english | ✗ |
| 392 | eynhallow located_in_or_next_to_body_of_water | atlantic_ocean | ✓ | atlantic_ocean | ✗ |
| 393 | powersite country | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 394 | side_arms_hyper_dyne genre | shoot_'em_up | ✓ | shoot_'em_up | ✗ |
| 395 | radu_i_of_wallachia spouse | kalinikia | ✓ | kalinikia | ✗ |
| 396 | mundi country | india | ✓ | india | ✗ |
| 397 | bccip chromosome | human_chromosome_10 | ✓ | human_chromosome_10 | ✗ |
| 398 | namibia:_the_struggle_for_liberation genre | war_film | ✓ | war_film | ✗ |
| 399 | the_narrow_road_to_the_deep_north author | richard_flanagan | ✓ | richard_flanagan | ✗ |
| 400 | pittosporum_dasycaulon taxon_rank | species | ✓ | species | ✗ |
| 401 | dean_stokes member_of_sports_team | armitage_90_f.c. | ✓ | armitage_90_f.c. | ✗ |
| 402 | odawara located_in_time_zone | utc+09:00 | ✓ | utc+09:00 | ✗ |
| 403 | movement_of_the_national_left instance_of | political_party | ✓ | political_party | ✗ |
| 404 | zen_in_the_united_states subclass_of | buddhism_in_the_united_st | ✓ | buddhism_in_the_united_st | ✗ |
| 405 | alex_whittle member_of_sports_team | liverpool_f.c. | ✓ | liverpool_f.c. | ✗ |
| 406 | crossings follows | little_things | ✓ | little_things | ✗ |
| 407 | kimberly_buys place_of_birth | sint-niklaas | ✓ | sint-niklaas | ✗ |
| 408 | emoción,_canto_y_guitarra performer | jorge_cafrune | ✓ | jorge_cafrune | ✗ |
| 409 | william_t._martin allegiance | confederate_states_of_ame | ✓ | confederate_states_of_ame | ✗ |
| 410 | darrin_pfeiffer country_of_citizenship | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 411 | srboljub_markušević occupation | association_football_mana | ✓ | association_football_mana | ✗ |
| 412 | le_mans distributor | national_general_pictures | ✓ | national_general_pictures | ✗ |
| 413 | agrostis_trachychlaena taxon_rank | species | ✓ | species | ✗ |
| 414 | jay_sparrow instance_of | human | ✓ | human | ✗ |
| 415 | acrobatic_dog-fight instance_of | video_game | ✓ | video_game | ✗ |
| 416 | la_chair_de_l'orchidée composer | fiorenzo_carpi | ✓ | fiorenzo_carpi | ✗ |
| 417 | brian_heward occupation | association_football_play | ✓ | association_football_play | ✗ |
| 418 | richard_steinheimer instance_of | human | ✓ | human | ✗ |
| 419 | sakurabashi_station connecting_line | shizuoka–shimizu_line | ✓ | shizuoka–shimizu_line | ✗ |
| 420 | waru cast_member | atsuko_sakuraba | ✓ | atsuko_sakuraba | ✗ |
| 421 | viktor_savelyev award_received | hero_of_socialist_labour | ✗ |  | — |
| 422 | edward_stanley,_2nd_baron_stanley_of_alderley give | edward | ✓ | edward | ✗ |
| 423 | bell_street_bus_station country | australia | ✓ | australia | ✗ |
| 424 | georges_dufayel instance_of | human | ✓ | human | ✗ |
| 425 | kağan_timurcin_konuk occupation | association_football_play | ✓ | association_football_play | ✗ |
| 426 | dhimitër_pasko country_of_citizenship | albania | ✓ | albania | ✗ |
| 427 | andersonville located_in_time_zone | eastern_time_zone | ✓ | eastern_time_zone | ✗ |
| 428 | oweekeno country | canada | ✓ | canada | ✗ |
| 429 | gavriel_zev_margolis place_of_death | new_york_city | ✓ | new_york_city | ✗ |
| 430 | ankfy1 chromosome | human_chromosome_17 | ✓ | human_chromosome_17 | ✗ |
| 431 | dr._wake's_patient original_language_of_film_or_tv | english | ✓ | english | ✗ |
| 432 | frank_henderson educated_at | university_of_idaho | ✓ | university_of_idaho | ✗ |
| 433 | uss_braziliera location_of_final_assembly | baltimore | ✓ | baltimore | ✗ |
| 434 | austin_reed instance_of | human | ✓ | human | ✗ |
| 435 | fran_brodić member_of_sports_team | croatia_national_under-18 | ✗ |  | — |
| 436 | m45_motorway terminus_location | watford_gap | ✓ | watford_gap | ✗ |
| 437 | ramshir located_in_the_administrative_territorial_ | central_district | ✓ | central_district | ✗ |
| 438 | échassières located_in_time_zone | utc+01:00 | ✓ | utc+01:00 | ✗ |
| 439 | yaroslav_deda member_of_sports_team | fc_volyn_lutsk | ✓ | fc_volyn_lutsk | ✗ |
| 440 | john_collier languages_spoken,_written_or_signed | english | ✓ | english | ✗ |
| 441 | fernando_de_moraes member_of_sports_team | australia_national_futsal | ✓ | australia_national_futsal | ✗ |
| 442 | trumaker_&_co. country | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 443 | bernard_malamud notable_work | the_magic_barrel | ✗ |  | — |
| 444 | dunkirk,_nottingham country | united_kingdom | ✓ | united_kingdom | ✗ |
| 445 | all_hands_on_deck part_of | aquarius | ✓ | aquarius | ✗ |
| 446 | musō_soseki languages_spoken,_written_or_signed | japanese | ✓ | japanese | ✗ |
| 447 | return_of_the_living_dead_part_ii cast_member | james_karen | ✓ | james_karen | ✗ |
| 448 | seven_men_from_now genre | western_film | ✓ | western_film | ✗ |
| 449 | patrick_m'boma given_name | patrick | ✓ | patrick | ✗ |
| 450 | æneas_mackenzie instance_of | human | ✓ | human | ✗ |
| 451 | northern_dancer color | bay | ✓ | bay | ✗ |
| 452 | list_of_uk_r&b_singles_chart_number_ones_of_2016 i | wikimedia_list_article | ✓ | wikimedia_list_article | ✗ |
| 453 | harry_potter_and_the_order_of_the_phoenix filming_ | turkey | ✓ | turkey | ✗ |
| 454 | ng_eng_hen instance_of | human | ✓ | human | ✗ |
| 455 | joaquín_argamasilla given_name | joaquín | ✓ | joaquín | ✗ |
| 456 | tim_castille member_of_sports_team | kansas_city_chiefs | ✓ | kansas_city_chiefs | ✗ |
| 457 | gabriela_silang country_of_citizenship | philippines | ✓ | philippines | ✗ |
| 458 | blake_berris place_of_birth | los_angeles | ✓ | los_angeles | ✗ |
| 459 | mike_sandbothe employer | berlin_university_of_the_ | ✓ | berlin_university_of_the_ | ✗ |
| 460 | lincoln_mks powered_by | petrol_engine | ✓ | petrol_engine | ✗ |
| 461 | tales_from_northumberland_with_robson_green countr | united_kingdom | ✓ | united_kingdom | ✗ |
| 462 | 2015–16_isthmian_league sport | association_football | ✓ | association_football | ✗ |
| 463 | ramon_d'abadal_i_de_vinyals educated_at | university_of_barcelona | ✓ | university_of_barcelona | ✗ |
| 464 | corsair country_of_origin | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 465 | hybothecus_flohri instance_of | taxon | ✓ | taxon | ✗ |
| 466 | chilean_navy country | chile | ✓ | chile | ✗ |
| 467 | tridens instance_of | taxon | ✓ | taxon | ✗ |
| 468 | sahar_youssef participant_of | 1984_summer_olympics | ✓ | 1984_summer_olympics | ✗ |
| 469 | rhododendron_phaeochrysum parent_taxon | rhododendron | ✓ | rhododendron | ✗ |
| 470 | lesley_garrett voice_type | soprano | ✓ | soprano | ✗ |
| 471 | fort_franklin_battlespace_laboratory located_in_th | massachusetts | ✓ | massachusetts | ✗ |
| 472 | rafael_barbosa_do_nascimento sport | association_football | ✓ | association_football | ✗ |
| 473 | nikola_aksentijević member_of_sports_team | vitesse | ✓ | vitesse | ✗ |
| 474 | 2017_tirreno–adriatico participating_team | bahrain-merida_2017 | ✓ | bahrain-merida_2017 | ✗ |
| 475 | ouray_mine instance_of | mine | ✓ | mine | ✗ |
| 476 | code_of_the_outlaw country_of_origin | united_states_of_america | ✓ | united_states_of_america | ✗ |
| 477 | x_factor_georgia original_network | rustavi_2 | ✓ | rustavi_2 | ✗ |
| 478 | those_who_were_hung_hang_here followed_by | modern_currencies | ✗ |  | — |
| 479 | anyamaru_tantei_kiruminzuu genre | shōjo | ✓ | shōjo | ✗ |
| 480 | bouchaib_el_moubarki member_of_sports_team | al_ahli_sc | ✓ | al_ahli_sc | ✗ |
| 481 | frits_zernike place_of_death | amersfoort | ✓ | amersfoort | ✗ |
| 482 | ashraf_choudhary place_of_birth | sialkot | ✓ | sialkot | ✗ |
| 483 | david_grant sport | association_football | ✓ | association_football | ✗ |
| 484 | the_good_night cast_member | penélope_cruz | ✗ |  | — |
| 485 | 1947_tour_de_france,_stage_1_to_stage_11 country | france | ✓ | france | ✗ |
| 486 | henry_stafford,_2nd_duke_of_buckingham child | elizabeth_stafford,_count | ✓ | elizabeth_stafford,_count | ✗ |
| 487 | 2005–06_ligue_magnus_season country | france | ✓ | france | ✗ |
| 488 | province_of_messina contains_administrative_territ | reitano | ✗ |  | — |
| 489 | evan_taylor member_of_sports_team | harbour_view_f.c. | ✓ | harbour_view_f.c. | ✗ |
| 490 | christina_hengster languages_spoken,_written_or_si | german | ✓ | german | ✗ |
| 491 | malegoude shares_border_with | seignalens | ✓ | seignalens | ✗ |
| 492 | magna_carta contributor(s)_to_the_creative_work_or | caroline_lucas | ✗ |  | — |
| 493 | wilshire located_in_the_administrative_territorial | california | ✓ | california | ✗ |
| 494 | nemanja_miletić member_of_sports_team | fk_sloga_kraljevo | ✗ |  | — |
| 495 | mainframe_sort_merge instance_of | software | ✓ | software | ✗ |
| 496 | harald_feller instance_of | human | ✓ | human | ✗ |
| 497 | steve_mcmanaman sport | association_football | ✓ | association_football | ✗ |
| 498 | max_speter given_name | max | ✓ | max | ✗ |
| 499 | gertrude_abercrombie employer | works_progress_administra | ✓ | works_progress_administra | ✗ |
| 500 | sriranjani occupation | actor | ✓ | actor | ✗ |

---

## Mode 4 — Complex Multi-Entity Comparison (200)

| # | Entity 1 | Gold 1 | Hit 1 | Entity 2 | Gold 2 | Hit 2 | Relation | Both |
|---|----------|--------|-------|----------|--------|-------|----------|------|
| 1 | karl_alois,_prince_l | prince_lichnowsky | ✓ | meriam_al_khalifa | house_of_al-khalifa | ✓ | family | ✓✓ |
| 2 | hd_170469_b | radial_velocity | ✓ | proxima_centauri_b | doppler_spectroscopy | ✓ | discovery_method | ✓✓ |
| 3 | moult | alain_tourret | ✓ | iceland | sigmundur_davíð_gunn | ✓ | head_of_government | ✓✓ |
| 4 | anthony_derosa | character_animation | ✓ | christer_fuglesang | physics | ✓ | academic_major | ✓✓ |
| 5 | warlock | marvel_universe | ✓ | alex_wilder | marvel_universe | ✓ | from_fictional_universe | ✓✓ |
| 6 | 1966–67_fußball-bund | rot-weiss_essen | ✓ | 2006–07_cypriot_seco | ermis_aradippou_fc | ✓ | relegated | ✓✓ |
| 7 | wakefield_kirkgate_r | bicycle_parking | ✓ | olmsted_point | parking_lot | ✓ | has_facility | ✓✓ |
| 8 | riksbron | gustaf_v_of_sweden | ✓ | 1994_winter_olympics | harald_v_of_norway | ✓ | officially_opened_by | ✓✓ |
| 9 | feels_like_love | dance_music | ✓ | roger_brown | country_music | ✓ | genre | ✓✓ |
| 10 | inductive_reasoning | deductive_reasoning | ✓ | anterograde_amnesia | retrograde_amnesia | ✓ | opposite_of | ✓✓ |
| 11 | lilacs_in_a_window | metropolitan_museum_ | ✓ | a_studio_at_les_bati | musée_d'orsay | ✓ | collection | ✓✓ |
| 12 | trans-mongolian_rail | darkhan | ✓ | japan_national_route | kita-kantō_expresswa | ✓ | connects_with | ✓✓ |
| 13 | mediastinal_neoplasm | mediastinum | ✓ | greater_trochanter | femur | ✓ | anatomical_location | ✓✓ |
| 14 | kaalo | rahul_ranade | ✓ | jamón_jamón | nicola_piovani | ✓ | composer | ✓✓ |
| 15 | sports_in_india | india | ✓ | 2014_in_romania | 2014 | ✓ | facet_of | ✓✓ |
| 16 | christmas_island | .cx | ✓ | chad | .td | ✓ | top-level_internet_domain | ✓✓ |
| 17 | bajo_de_la_carpa_for | anacleto_formation | ✓ | scalby_formation | cornbrash_formation | ✓ | underlies | ✓✓ |
| 18 | rbs_23 | semi-automatic_comma | ✓ | skyflash | semi-active_radar_ho | ✓ | guidance_system | ✓✓ |
| 19 | tetrahemihexahedron | triangle | ✓ | square_antiprism | quadrilateral | ✓ | base | ✓✓ |
| 20 | marco_polo_junior_ve | bobby_rydell | ✓ | open_season | cody_cameron | ✓ | voice_actor | ✓✓ |
| 21 | national_education_a | george_washington_un | ✓ | katharine_brush | beinecke_rare_book_& | ✓ | archives_at | ✓✓ |
| 22 | honda_p50 | air-cooled_engine | ✓ | t-80 | turboshaft | ✓ | powered_by | ✓✓ |
| 23 | 1980_gent–wevelgem | jo_maas | ✓ | 2017_tour_of_flander | john_degenkolb | ✓ | general_classification_of | ✓✓ |
| 24 | stadsholmen | gamla_stan | ✓ | battle_of_nineveh | nineveh | ✓ | location | ✓✓ |
| 25 | luossajärvi | nutrient_pollution | ✓ | yngaren | nutrient_pollution | ✓ | significant_environmental | ✓✓ |
| 26 | age_of_chivalry | source | ✓ | mechwarrior:_living_ | cryengine | ✓ | software_engine | ✓✓ |
| 27 | anatoli_fedotov | soviet_union | ✓ | thailand_men's_natio | thailand | ✓ | country_for_sport | ✓✓ |
| 28 | m._kumaran_s | amma_nanna_o_tamila_ | ✓ | the_anna_cross | anna_on_the_neck | ✓ | based_on | ✓✓ |
| 29 | pechlaurier_lock | canal_du_midi | ✓ | ognon_lock | canal_du_midi | ✓ | located_on_linear_feature | ✓✓ |
| 30 | chebotarev_theorem_o | nikolai_chebotaryov | ✓ | hausdorff_paradox | felix_hausdorff | ✓ | proved_by | ✓✓ |
| 31 | caesar_martinez | the_walking_dead | ✓ | darth_bane | star_wars_expanded_t | ✓ | from_fictional_universe | ✓✓ |
| 32 | bokermannohyla_clare | brazil | ✓ | tarucus_thespis | south_africa | ✓ | endemic_to | ✓✓ |
| 33 | you,_me_and_dupree | universal_studios | ✗ | the_brothers_bloom | the_weinstein_compan | ✓ | production_company | ✗ |
| 34 | shimano_racing | hidenori_nodera | ✓ | sg_quelle_fürth | thomas_adler | ✓ | head_coach | ✓✓ |
| 35 | hohniesen | bernese_alps | ✓ | cunurana | la_raya_mountain_ran | ✓ | mountain_range | ✓✓ |
| 36 | alytus | alytus_district_muni | ✓ | vostochny_district | moscow_oblast | ✓ | enclave_within | ✓✓ |
| 37 | mercury-atlas_8 | low_earth_orbit | ✓ | jamal_201 | geostationary_orbit | ✓ | type_of_orbit | ✓✓ |
| 38 | angela_petrelli | precognition | ✓ | warren_worthington_i | flight | ✓ | superhuman_feature_or_abi | ✓✓ |
| 39 | chia_seed | salvia_hispanica | ✓ | iroko | milicia_regia | ✓ | natural_product_of_taxon | ✓✓ |
| 40 | zanthoxylum_simulans | sichuan_pepper | ✓ | prunus_subg._cerasus | cherry | ✓ | this_taxon_is_source_of | ✓✓ |
| 41 | pater_noster_lightho | submarine_power_cabl | ✓ | stora_karlsö_lightho | electricity | ✓ | source_of_energy | ✓✓ |
| 42 | lamberto_visconti_di | ubaldo_of_gallura | ✓ | jan_poštulka | tomáš_poštulka | ✓ | child | ✓✓ |
| 43 | stig_blomqvist | björn_cederberg | ✓ | sébastien_ogier | julien_ingrassia | ✓ | co-driver | ✓✓ |
| 44 | amalgamated_society_ | amalgamated_society_ | ✓ | lutheran_church–miss | federal_communicatio | ✓ | plaintiff | ✓✓ |
| 45 | spacex_crs-10 | spacex | ✓ | spacex_crs-8 | spacex | ✓ | launch_contractor | ✓✓ |
| 46 | hans_von_pechmann | heinrich_limpricht | ✓ | arthur_b._robinson | martin_kamen | ✓ | doctoral_advisor | ✓✓ |
| 47 | joaquín_"el_chapo"_g | ignacio_coronel_vill | ✓ | dragan_babić | liv_ullmann | ✓ | partner | ✓✓ |
| 48 | wilhelm-ferdinand_ga | world_war_ii | ✓ | smith_carbine | american_civil_war | ✓ | conflict | ✓✓ |
| 49 | scrobipalpa_spergula | species | ✓ | paracymoriza_albalis | species | ✓ | taxon_rank | ✓✓ |
| 50 | mary_chind-willie | mary | ✓ | heinz_kohut | heinz | ✓ | given_name | ✓✓ |
| 51 | fiat_a.22 | v12 | ✓ | bmw_iiia | straight-six | ✓ | engine_configuration | ✓✓ |
| 52 | soyuz_tm-5 | aleksandr_panayotov_ | ✓ | sts-70 | nancy_j._currie | ✓ | crew_member | ✓✓ |
| 53 | neil_young_journeys | toronto | ✓ | bound_and_gagged | fort_lee | ✓ | filming_location | ✓✓ |
| 54 | borovitskaya | biblioteka_imeni_len | ✓ | chistye_prudy_metro_ | turgenevskaya | ✓ | interchange_station | ✓✓ |
| 55 | hartog_jacob_hamburg | albert_szent-györgyi | ✓ | wilhelm_eduard_weber | eduard_riecke | ✓ | doctoral_student | ✓✓ |
| 56 | belize | .bz | ✓ | saint_vincent_and_th | .vc | ✓ | top-level_internet_domain | ✓✓ |
| 57 | winkipop | female_organism | ✓ | pourparler | female_organism | ✓ | sex_or_gender | ✓✓ |
| 58 | wprb | princeton | ✓ | wqbt | savannah | ✓ | licensed_to_broadcast_to | ✓✓ |
| 59 | louis_massignon | mysticism | ✓ | thomas_aquinas | mysticism | ✓ | lifestyle | ✓✓ |
| 60 | historicity | philosophy | ✓ | caucasus | caucasology | ✓ | studied_by | ✓✓ |
| 61 | rreb1 | human_chromosome_6 | ✓ | atf1 | human_chromosome_12 | ✓ | chromosome | ✓✓ |
| 62 | natal_free-tailed_ba | mauritius_island | ✓ | tympanocryptis_penta | queensland | ✓ | endemic_to | ✓✓ |
| 63 | oratory_of_san_giaco | roman_catholic_archd | ✓ | balsfjord_church | diocese_of_nord-hålo | ✓ | diocese | ✓✓ |
| 64 | beenverified | indeed | ✓ | arash | youtube | ✓ | website_account_on | ✓✓ |
| 65 | brummie | birmingham | ✓ | ubykh | ubykhia | ✓ | indigenous_to | ✓✓ |
| 66 | self-esteem | rosenberg_self-estee | ✓ | frequency | hertz | ✓ | measured_by | ✓✓ |
| 67 | neutering | sex | ✓ | 2019_world_men's_han | man | ✓ | applies_to_part | ✓✓ |
| 68 | irish_newfoundlander | irish_diaspora | ✓ | indians_in_kenya | non-resident_indian_ | ✓ | diaspora | ✓✓ |
| 69 | a'wesome | hyuna | ✓ | under_one_roof | hunters_&_collectors | ✓ | performer | ✓✓ |
| 70 | marvin_l._esch | wayne_state_universi | ✓ | tim_vickery | bbc | ✓ | employer | ✓✓ |
| 71 | streptanthus_niger | basionym | ✓ | dodonaea_angustifoli | basionym | ✓ | subject_has_role | ✓✓ |
| 72 | la_delatora | nathán_pinzón | ✓ | marquis_preferred | adolphe_menjou | ✓ | cast_member | ✓✓ |
| 73 | middle_egyptian | verb–subject–object | ✓ | kerinci | agglutinative_langua | ✓ | linguistic_typology | ✓✓ |
| 74 | eugenia_p._butler | eugenia_butler | ✓ | matsudaira_nobuyasu | tsukiyama-dono | ✓ | mother | ✓✓ |
| 75 | quintus_laronius | roman_republic | ✓ | aristippus | hellenistic_period | ✓ | time_period | ✓✓ |
| 76 | victoria_rooms,_bris | bristol | ✓ | lincoln_tomb | springfield | ✓ | located_in_the_administra | ✓✓ |
| 77 | carlo_maderno | francesco_borromini | ✓ | heinz_hitler | geli_raubal | ✓ | relative | ✓✓ |
| 78 | curaçao | central_bank_of_cura | ✓ | brazilian_cruzado_no | central_bank_of_braz | ✓ | central_bank | ✓✓ |
| 79 | 1956–57_northern_rug | england | ✓ | 2004–05_western_foot | england | ✓ | operating_area | ✓✓ |
| 80 | street_fighter_ii'_t | zilog_z80 | ✓ | dynamic_ski | zilog_z80 | ✓ | cpu | ✓✓ |
| 81 | gymnopilus_parrumbal | saprotrophic_nutriti | ✓ | trametes_versicolor | saprotrophic_nutriti | ✓ | mushroom_ecological_type | ✓✓ |
| 82 | bayram | variable | ✓ | fossil_fools_day | april_1 | ✓ | day_in_year_for_periodic_ | ✓✓ |
| 83 | yngaren | nutrient_pollution | ✓ | luossajärvi | nutrient_pollution | ✓ | significant_environmental | ✓✓ |
| 84 | 2009–10_romanian_hoc | ice_hockey | ✓ | cho_so-hyun | association_football | ✓ | sport | ✓✓ |
| 85 | ted_conferences | chris_anderson | ✓ | documenta_7 | rudi_fuchs | ✓ | curator | ✓✓ |
| 86 | supernovae_in_fictio | supernova | ✓ | binary_stars_in_fict | binary_star | ✓ | fictional_analog_of | ✓✓ |
| 87 | simba | russ_edmonds | ✓ | african_times_and_or | marcus_garvey | ✓ | contributor(s)_to_the_cre | ✓✓ |
| 88 | aulus_postumius_albi | roman_republic | ✓ | archidamus_i | classical_antiquity | ✓ | time_period | ✓✓ |
| 89 | 15068_wiegert | hilda_group | ✓ | 2003_sq317 | haumea_family | ✓ | asteroid_family | ✓✓ |
| 90 | thame_abbey | westminster_abbey | ✓ | l'aumône_abbey | cîteaux_abbey | ✓ | mother_house | ✓✓ |
| 91 | chest | physical_object | ✓ | anti–email_spam_tech | electronic_spam | ✓ | has_immediate_cause | ✓✓ |
| 92 | claude-françois-alex | catholicism | ✓ | oliver_o'grady | catholic_church | ✓ | religion | ✓✓ |
| 93 | ivan_martin_jirous | charter_77 | ✓ | treaty_of_lübeck | albrecht_von_wallens | ✓ | signatory | ✓✓ |
| 94 | short_gastric_artery | splenic_artery | ✓ | occipital_artery | external_carotid_art | ✓ | anatomical_branch_of | ✓✓ |
| 95 | athletics_at_the_198 | paralympic_games | ✓ | mythbusters,_2004_se | mythbusters | ✓ | part_of | ✓✓ |
| 96 | psilocybe_weilii | brown | ✓ | mycena_haematopus | white | ✓ | spore_print_color | ✓✓ |
| 97 | 1996_indiana_guberna | governor_of_indiana | ✓ | 1956_finnish_preside | president_of_finland | ✓ | office_contested | ✓✓ |
| 98 | portal:connecticut | connecticut | ✓ | portal:cetaceans | cetacea | ✓ | wikimedia_portal's_main_t | ✓✓ |
| 99 | karelo-finnish_sovie | anthem_of_the_karelo | ✓ | mauritania | national_anthem_of_m | ✓ | anthem | ✓✓ |
| 100 | portal:iraq | iraq | ✓ | portal:schleswig-hol | schleswig-holstein | ✓ | wikimedia_portal's_main_t | ✓✓ |
| 101 | united_kingdom | monarch_of_the_unite | ✓ | dominion_of_india | governor-general_of_ | ✓ | office_held_by_head_of_st | ✓✓ |
| 102 | blue_dress_of_meagan | meagan_good | ✓ | minotaur | space_and_missile_sy | ✓ | commissioned_by | ✓✓ |
| 103 | valery | walery | ✓ | the_thaw | the_thaw | ✓ | different_from | ✓✓ |
| 104 | black_clock | steve_erickson | ✓ | spy | graydon_carter | ✓ | editor | ✓✓ |
| 105 | federico_borromeo | the_betrothed | ✓ | orlando_furioso | alcina | ✓ | depicted_by | ✓✓ |
| 106 | michou | montmartre | ✓ | miloslav_mečíř,_jr. | bratislava | ✓ | residence | ✓✓ |
| 107 | 1951_dutch_grand_pri | andré_pilette | ✓ | aurora | maleficent | ✓ | significant_person | ✓✓ |
| 108 | stranov | cultural_monument_of | ✓ | james's_fort | national_monument_of | ✓ | heritage_designation | ✓✓ |
| 109 | maria_anna_of_savoy | house_of_savoy | ✓ | henry_ii_of_castile | house_of_trastámara | ✓ | family | ✓✓ |
| 110 | gamera | gamera | ✓ | jeremy_peterson | hollyoaks | ✓ | present_in_work | ✓✓ |
| 111 | hammarby_fotboll | kennedy_bakircioglu | ✓ | oulun_kärpät | lasse_kukkonen | ✓ | captain | ✓✓ |
| 112 | the_rebel | rebellion | ✓ | i.d. | association_football | ✓ | main_subject | ✓✓ |
| 113 | (13985)_1992_uh3 | (13986)_1992_wa4 | ✓ | 1889_in_poetry | 1890_in_poetry | ✓ | followed_by | ✓✓ |
| 114 | buster_jones | jones | ✓ | don_kennedy | kennedy | ✓ | family_name | ✓✓ |
| 115 | a_bell_for_adano | george_salter | ✓ | the_devil_in_a_fores | david_palladini | ✓ | cover_art_by | ✓✓ |
| 116 | charlie_hebdo_issue_ | georges_wolinski | ✓ | keep_the_giraffe_bur | peter_goodfellow | ✓ | illustrator | ✓✓ |
| 117 | portal:democratic_re | democratic_republic_ | ✓ | portal:iraq | iraq | ✓ | wikimedia_portal's_main_t | ✓✓ |
| 118 | st_peter's_church,_l | peter | ✓ | piano_sonata_no._3 | joseph_haydn | ✓ | dedicated_to | ✓✓ |
| 119 | ovarian_artery | testicular_artery | ✓ | testicular_artery | ovarian_artery | ✓ | sexually_homologous_with | ✓✓ |
| 120 | the_devil's_arithmet | brittany_murphy | ✓ | jai_jawan | akkineni_nageswara_r | ✓ | cast_member | ✓✓ |
| 121 | the_neverending_stor | michael_ende | ✓ | 1408 | stephen_king | ✓ | after_a_work_by | ✓✓ |
| 122 | serratus_anterior_mu | trapezius_muscle | ✓ | longissimus | rectus_abdominis_mus | ✓ | antagonist_muscle | ✓✓ |
| 123 | left,_ecology_and_fr | nichi_vendola | ✓ | house_of_freedoms | silvio_berlusconi | ✓ | chairperson | ✓✓ |
| 124 | nicolae_grigorescu | charles-françois_dau | ✓ | elizabeth_laird | emil_warburg | ✓ | influenced_by | ✓✓ |
| 125 | erskine | list_of_people_with_ | ✓ | prime_minister_of_ru | list_of_heads_of_gov | ✓ | has_list | ✓✓ |
| 126 | guinean_franc | central_bank_of_the_ | ✓ | brazilian_cruzado_no | central_bank_of_braz | ✓ | central_bank | ✓✓ |
| 127 | battle_of_mill_sprin | mill_springs_confede | ✓ | operation_market_gar | operation_market_gar | ✓ | order_of_battle | ✓✓ |
| 128 | list_of_the_neverend | caca | ✓ | catholic_university_ | university | ✓ | topic's_main_category | ✓✓ |
| 129 | cello_concerto_no._1 | a_minor | ✓ | sunflower_slow_drag | b-flat_major | ✓ | tonality | ✓✓ |
| 130 | louise_seidler | gerhard_von_kügelgen | ✓ | hammad_ibn_salamah | ibrahim_al-nakhai | ✓ | student_of | ✓✓ |
| 131 | cedar_rapids_kernels | minnesota_twins | ✓ | maría_itatí_castaldi | argentina_national_b | ✓ | parent_club | ✓✓ |
| 132 | john_fane | 1st_united_kingdom_p | ✓ | gerald_blidstein | israel_academy_of_sc | ✓ | member_of | ✓✓ |
| 133 | crtc3 | homo_sapiens | ✓ | slmap | homo_sapiens | ✓ | found_in_taxon | ✓✓ |
| 134 | san_marino | guerrino_zanotti | ✓ | government_of_the_8t | george_v | ✓ | head_of_state | ✓✓ |
| 135 | 1._hfk_olomouc | oldřich_machala | ✓ | unione_sportiva_avel | massimo_rastelli | ✓ | head_coach | ✓✓ |
| 136 | ottoman_socialist_pa | international_instit | ✓ | thomas_spring_rice,_ | national_library_of_ | ✓ | archives_at | ✓✓ |
| 137 | hugh_macdonald | louis | ✓ | frank_kleffner | louis | ✓ | employer washington_unive | ✓✓ |
| 138 | dentsu | kakaku.com | ✓ | axiata | celcom | ✓ | owner_of | ✓✓ |
| 139 | lufthansa_cityline | star_alliance | ✓ | jal_express | oneworld | ✓ | airline_alliance | ✓✓ |
| 140 | i3 | continuous_integrati | ✓ | util-linux | continuous_integrati | ✓ | software_quality_assuranc | ✓✓ |
| 141 | tyrrhenian_sea | italy | ✓ | caspian_sea | turkmenistan | ✓ | basin_country | ✓✓ |
| 142 | i_am_a_catalan | pau_casals | ✓ | i'll_be_back | terminator | ✓ | speaker | ✓✓ |
| 143 | barrow's_inequality | triangle | ✓ | pascal's_theorem | hexagon | ✓ | statement_describes | ✓✓ |
| 144 | britney_spears:_live | english | ✓ | gatra | indonesian | ✓ | language_of_work_or_name | ✓✓ |
| 145 | paintings_attributed | chiaroscuro | ✓ | management | public_administratio | ✓ | fabrication_method | ✓✓ |
| 146 | flag_of_the_united_s | rectangle | ✓ | ikurriña | rectangle | ✓ | shape | ✓✓ |
| 147 | university_of_girona | xarxa_vives_d'univer | ✓ | midnapore_medical_co | west_bengal_universi | ✓ | affiliation | ✓✓ |
| 148 | conjuring | james_randi | ✓ | episodes_of_the_cuba | che_guevara | ✓ | author | ✓✓ |
| 149 | chromhidrosis | sweat | ✓ | tomato_ringspot_viru | solanum_lycopersicum | ✓ | afflicts | ✓✓ |
| 150 | gambia | coat_of_arms_of_the_ | ✓ | republic_of_buryatia | coat_of_arms_of_the_ | ✓ | coat_of_arms | ✓✓ |
| 151 | øystein_hedstrøm | oslo | ✓ | charles_grant,_1st_b | london | ✓ | work_location | ✓✓ |
| 152 | spring_street_statio | 6 | ✓ | gare_de_saint-malo | ter_bretagne | ✓ | connecting_service | ✓✓ |
| 153 | a.g._huntsman_award_ | royal_society_of_can | ✓ | élie_cartan_prize | french_academy_of_sc | ✓ | conferred_by | ✓✓ |
| 154 | general_motors | new_york_stock_excha | ✓ | unum | new_york_stock_excha | ✓ | stock_exchange | ✓✓ |
| 155 | john_benbow | jamaica_station | ✓ | étienne_maurice_géra | 2nd_army_corps | ✓ | commander_of | ✓✓ |
| 156 | the_bed_of_procruste | nassim_nicholas_tale | ✓ | d-live!! | ryōji_minagawa | ✓ | author | ✓✓ |
| 157 | maternal_mortality_r | world_health_organiz | ✓ | auden_group | w._h._auden | ✓ | used_by | ✓✓ |
| 158 | ppf_group | home_credit | ✓ | alphabet_inc. | google_fiber | ✓ | subsidiary | ✓✓ |
| 159 | bjarne | june_18 | ✓ | rikard | february_7 | ✓ | name_day | ✓✓ |
| 160 | list_of_supermarket_ | supermarket | ✓ | line_of_succession_t | human | ✓ | is_a_list_of | ✓✓ |
| 161 | scream | bob_weinstein | ✓ | the_treasure_knights | joseph_vilsmaier | ✓ | executive_producer | ✓✓ |
| 162 | big_karnak | motorola_68000 | ✓ | dance_dance_revoluti | reduced_instruction_ | ✓ | cpu | ✓✓ |
| 163 | falange_española_tra | falange_española_de_ | ✓ | lix_legislature_of_t | lviii_legislature_of | ✓ | replaces | ✓✓ |
| 164 | saint_roch | saint | ✓ | alpaïs_of_cudot | saint | ✓ | canonization_status | ✓✓ |
| 165 | lost_in_blue:_shipwr | hudson_soft | ✓ | naviserver | navisoft | ✓ | developer | ✓✓ |
| 166 | bellevigny | le_poiré-sur-vie | ✓ | velká_chmelištná | václavy | ✓ | shares_border_with | ✓✓ |
| 167 | punker_of_rohrbach | malleus_maleficarum | ✓ | lizzie_twigg | ulysses | ✓ | present_in_work | ✓✓ |
| 168 | chrysler_tc_by_maser | chrysler | ✓ | ford_versailles | ford_motor_company | ✓ | brand | ✓✓ |
| 169 | haninge_municipality | meeri_wasberg | ✓ | i._k._gujral_ministr | i._k._gujral | ✓ | head_of_government | ✓✓ |
| 170 | prime_minister_of_et | list_of_heads_of_gov | ✓ | emperor_of_japan | list_of_emperors_of_ | ✓ | has_list | ✓✓ |
| 171 | craig_mcewan | pollok_f.c. | ✓ | yuriy_romenskyi | ukraine_national_foo | ✓ | member_of_sports_team | ✓✓ |
| 172 | 19572_leahmarie | asteroid_belt | ✓ | 2464_nordenskiöld | asteroid_belt | ✓ | minor_planet_group | ✓✓ |
| 173 | the_age_of_bronze | exposition_universel | ✓ | two_running_girls | antipodeans | ✓ | exhibition_history | ✓✓ |
| 174 | seberuang | agglutinative_langua | ✓ | kypchak_languages | agglutinative_langua | ✓ | linguistic_typology | ✓✓ |
| 175 | beijing–shenyang_hig | overhead_line | ✓ | borsdorf–coswig_rail | 15_kv,_16.7_hz_ac_ra | ✓ | type_of_electrification | ✓✓ |
| 176 | jean-claude_romand | life_imprisonment | ✓ | corinne_luchaire | indignité_nationale | ✓ | penalty | ✓✓ |
| 177 | bon_voyage! | carroll_clark | ✓ | the_happiest_million | john_b._mansbridge | ✓ | art_director | ✓✓ |
| 178 | uscgc_knight_island | key_west | ✓ | piano_land | london | ✓ | home_port | ✓✓ |
| 179 | perceptive_software | lenexa | ✓ | kvint | tiraspol | ✓ | headquarters_location | ✓✓ |
| 180 | reform_movement | alliance_of_liberals | ✓ | farin_urlaub | die_ärzte | ✓ | member_of | ✓✓ |
| 181 | big_biz_tycoon_2 | mouse | ✓ | star_trigon | joystick | ✓ | input_method | ✓✓ |
| 182 | death_defying_acts | harry_houdini | ✓ | five_ashore_in_singa | hubert_bonisseur_de_ | ✓ | characters | ✓✓ |
| 183 | phorcys | religion_in_ancient_ | ✓ | krotos | religion_in_ancient_ | ✓ | worshipped_by | ✓✓ |
| 184 | tsushima_maru | uss_bowfin | ✓ | sultanate_of_damagar | conquest | ✓ | cause_of_destruction | ✓✓ |
| 185 | lufthansa_italia | star_alliance | ✓ | ba_connect | oneworld | ✓ | airline_alliance | ✓✓ |
| 186 | oued_ed-dahab_provin | sahrawi_arab_democra | ✓ | glandaz_point | argentina | ✓ | territory_claimed_by | ✓✓ |
| 187 | astoria | river_thames | ✓ | monte_subasio | apennine_mountains | ✓ | located_on_terrain_featur | ✓✓ |
| 188 | wanted:_dead_or_aliv | single-camera_setup | ✓ | lucifer | single-camera_setup | ✓ | camera_setup | ✓✓ |
| 189 | ecknach | paar | ✓ | hainerbach | mangfall | ✓ | mouth_of_the_watercourse | ✓✓ |
| 190 | royal_villa_of_monza | neoclassical_archite | ✓ | bruce-briggs_brick_b | renaissance_revival_ | ✓ | architectural_style | ✓✓ |
| 191 | godzilla_vs._hedorah | japan | ✓ | bachelorette | new_york_city | ✓ | filming_location | ✓✓ |
| 192 | sofia_kovalevskaya | cauchy–kowalevski_th | ✓ | robert_a.m._stern_ar | 15_central_park_west | ✓ | notable_work | ✓✓ |
| 193 | ryan_m | shoulder_wing | ✓ | o-1_bird_dog | monoplane | ✓ | wing_configuration | ✓✓ |
| 194 | peter_wambach | harrisburg | ✓ | arthur_le_moyne_de_l | paris | ✓ | work_location | ✓✓ |
| 195 | zeferino_vaz | university_of_são_pa | ✓ | andrew_blake | university_of_oxford | ✓ | employer | ✓✓ |
| 196 | libertador_general_s | general_artigas_brid | ✓ | northampton_street_b | easton–phillipsburg_ | ✓ | next_crossing_upstream | ✓✓ |
| 197 | diabetic_angiopathy | diabetes_mellitus | ✓ | gulf_war_oil_spill | gulf_war | ✓ | has_cause | ✓✓ |
| 198 | tagus_river | entrepeñas_reservoir | ✓ | rapa_river | laitaure | ✓ | lakes_on_river | ✓✓ |
| 199 | how_to_play_golf | bill_justice | ✗ | the_light_in_the_for | robert_o._cook | ✓ | film_crew_member | ✗ |
| 200 | president_of_nigeria | nigeria | ✓ | 29th_parliament_of_o | ontario | ✓ | applies_to_jurisdiction | ✓✓ |

---

*Generated by benchmark_reasoning.py · A8.1 Two-Tier Emergent Routing*